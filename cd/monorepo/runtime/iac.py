"""Bounded saved-plan executor for pinned trusted roots, no SDK mutation fallback.

The catalog is Blueprint-owned, not repository configuration. Blocked capability
rows cannot execute. All workspaces/plans/state/provider output remain private;
only safe aggregate counts leave this module. Host authorization and canonical
source regeneration are required upstream, not replaced by JSON validation.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

from contracts import ContractError, canonical_bytes, digest
from executor import ExecutionError, Runner
from operations import validate_operation


# Exact fixed Blueprint shared operation implementation, not source PYTHONPATH.
_shared_path=Path(__file__).resolve().parents[2]/'deploy/common/iac/operations.py'
_shared_spec=importlib.util.spec_from_file_location('cloudopsworks_native_iac_operations',_shared_path)
_shared=importlib.util.module_from_spec(_shared_spec)
_shared_spec.loader.exec_module(_shared)


class IaCError(RuntimeError):
    pass


def _run(executor, argv, *, cwd, env, codes=(0,)):
    try:
        result = executor.run(argv, cwd=cwd, env=env)
    except ExecutionError:
        raise IaCError('iac_process_failed') from None
    if result.returncode not in codes:
        raise IaCError('iac_process_failed')
    return result


def module_tree(root, files):
    h = hashlib.sha256()
    if not files or files != sorted(set(files)):
        raise IaCError('iac_catalog_files')
    for name in files:
        if (not isinstance(name,str) or name.startswith('/') or '\\' in name
                or any(p in ('','..','.') for p in name.split('/'))):
            raise IaCError('iac_catalog_files')
        path = root / name
        if any(p.is_symlink() for p in [path,*path.parents]) or not path.is_file() or path.stat().st_size > 4*1024*1024:
            raise IaCError('iac_catalog_files')
        h.update(name.encode()+b'\0'+path.read_bytes()+b'\0')
    return 'sha256:'+h.hexdigest()


def execution_tree(blueprint_root,row):
    """Bind the authoritative chart bytes, without creating a source chart fork."""
    root=Path(blueprint_root)
    source=module_tree(root/row['path'],row['files'])
    if 'chartPath' not in row:return source
    if row['chartPath']!='kubernetes/helm/charts':raise IaCError('iac_authoritative_chart')
    chart=root/row['chartPath']
    actual=sorted(p.relative_to(chart).as_posix() for p in chart.rglob('*') if p.is_file() or p.is_symlink())
    if actual!=row.get('chartFiles'):raise IaCError('iac_chart_inventory')
    return digest({'module':source,'authoritativeChart':module_tree(chart,actual)})


def verify_saved_plan(value, *, operation, addresses, owner_digest, previously_owned, replacements=(), apply_deletes=()):
    """Inspect private `tofu show -json` before apply; never emit raw values."""
    if not isinstance(value,dict) or value.get('errored') is True:
        raise IaCError('iac_plan_invalid')
    counts = dict(create=0, update=0, delete=0, unchanged=0)
    def matches(address, patterns):
        return address in patterns or any(a.endswith('[*]') and address.startswith(a[:-3]+'[') and address.endswith(']') for a in patterns)
    for change in value.get('resource_changes', []):
        if not isinstance(change,dict) or change.get('mode') not in ('managed','data'):
            raise IaCError('iac_plan_invalid')
        action = change.get('change',{})
        actions = action.get('actions')
        if change.get('mode') == 'data':
            if actions not in (['read'],['no-op']):
                raise IaCError('iac_external_parent_mutation')
            continue
        address = change.get('address','')
        permitted = matches(address,addresses)
        if not permitted or action.get('importing') is not None or action.get('generated_config'):
            raise IaCError('iac_unowned_plan_address')
        replacing = actions in (['create','delete'],['delete','create'])
        if replacing:
            if operation == 'destroy' or not matches(address,replacements) or address not in previously_owned:
                raise IaCError('iac_replacement_requires_review')
        elif actions not in (['no-op'],['create'],['update'],['delete']):
            raise IaCError('iac_replacement_requires_review')
        before, after = action.get('before') or {}, action.get('after') or {}
        if actions != ['create'] and address not in previously_owned:
            raise IaCError('iac_unowned_existing_resource')
        if operation == 'destroy':
            if actions not in (['delete'],['no-op']):
                raise IaCError('iac_destroy_scope')
        elif actions == ['delete'] and not matches(address,apply_deletes):
            raise IaCError('iac_apply_delete_scope')
        # Explicit tags where the chosen resource supports them bind ownership.
        # Other resource types require their exact saved-state address above.
        for state in (before, after):
            tags = state.get('tags')
            if tags and tags.get('cloudopsworks-owner') != owner_digest:
                raise IaCError('iac_owner_tag_mismatch')
        if replacing:
            counts['create'] += 1
            counts['delete'] += 1
        elif actions == ['no-op']:
            counts['unchanged'] += 1
        else:
            counts[actions[0]] += 1
    return counts


def verify_appengine_plan(value, handle, *, previously_owned):
    """Enforce the reviewed whole-service boundary on private saved-plan data.

    This is necessary, not sufficient: independently verified exclusive service
    inventory/history and the operator single-writer boundary remain upstream.
    A provider plan alone cannot prove absence of another pipeline or survivor.
    """
    if handle['moduleId'] != 'gcp-appengine':
        return
    resource=handle['resourceIdentity']
    if (handle['ownership']!='managed' or resource.get('service') in (None,'','default')
            or resource.get('appEnvironment') not in ('standard','flexible')):
        raise IaCError('iac_appengine_exclusive_service_required')
    types=('google_app_engine_standard_app_version','google_app_engine_flexible_app_version')
    expected=types[0 if resource['appEnvironment']=='standard' else 1]+'.component[0]'
    old_versions={address for address in previously_owned if any(address.startswith(t+'.') for t in types)}
    if old_versions and old_versions!={expected}:
        raise IaCError('iac_appengine_cross_mode_or_unknown_history')
    found=False
    for change in value.get('resource_changes',[]):
        if change.get('mode')!='managed' or not any(change.get('address','').startswith(t+'.') for t in types):
            continue
        if change['address']!=expected:
            raise IaCError('iac_appengine_cross_mode_or_unknown_history')
        found=True;action=change.get('change',{});actions=action.get('actions')
        if actions==['create','delete']:
            raise IaCError('iac_appengine_create_before_destroy_forbidden')
        if actions not in (['create'],['update'],['delete'],['no-op'],['delete','create']):
            raise IaCError('iac_appengine_plan_invalid')
        for side in ('before','after'):
            state=action.get(side)
            if state is None:
                continue
            if (state.get('project')!=resource['project'] or state.get('service')!=resource['service']
                    or state.get('delete_service_on_destroy') is not True
                    or state.get('noop_on_destroy') is not False):
                raise IaCError('iac_appengine_unverified_service_history')
        unknown=action.get('after_unknown',{})
        if any(unknown.get(k) for k in ('project','service','delete_service_on_destroy','noop_on_destroy')):
            raise IaCError('iac_appengine_unknown_service_boundary')
    if not found:
        raise IaCError('iac_appengine_version_plan_missing')


def native_backend(handle):
    """Fixed normalized native backend fields only; never credentials or raw YAML."""
    source = handle['backend']
    maps = {
        's3': {'bucket':'bucket','key':'key','region':'region','encrypt':'encrypt',
               'kmsKeyId':'kms_key_id','dynamodbTable':'dynamodb_table','useLockfile':'use_lockfile',
               'workspaceKeyPrefix':'workspace_key_prefix'},
        'gcs': {'bucket':'bucket','prefix':'prefix','kmsEncryptionKey':'kms_encryption_key'},
        'azurerm': {'resourceGroupName':'resource_group_name','storageAccountName':'storage_account_name',
                    'containerName':'container_name','key':'key','useOidc':'use_oidc','useAzureadAuth':'use_azuread_auth'},
    }
    kind = source['kind']
    if kind not in maps:
        raise IaCError('iac_backend_kind')
    result = {native:source[name] for name,native in maps[kind].items() if source.get(name) is not None}
    return {'terraform':{'backend':{kind:result}}}


class IaCExecutor:
    def __init__(self, blueprint_root, catalog, *, executor=None, tofu='tofu', terragrunt='terragrunt'):
        self.root = Path(blueprint_root).resolve()
        # A caller must supply the pinned central catalog, never a PR manifest.
        self.catalog = catalog
        self.executor = executor or Runner(inherit_environment=False)
        self.tofu, self.terragrunt = tofu, terragrunt

    def execute(self, plan, *, canonical, store, resource_claims, existing,
                values, credentials, verify_ready=None, expected_state_digest=None, before_apply=None, verify_applied=None):
        """`existing` is fresh read-only provider identity/owner evidence.

        Upstream must serialize repository state ownership operations using the
        fixed concurrency contract, independently verify the host/caller and
        regenerate `canonical` from immutable reviewed data before resolving
        protected credentials. Neither argument is obtained from PR artifacts.
        """
        validate_operation(plan, canonical=canonical)
        handle = plan['stateHandle']; operation = plan['operation']
        row = self.catalog.get('modules',{}).get(handle['moduleId'])
        if not row or row.get('activationBlocked') is not False:
            raise IaCError('iac_capability_blocked')
        source = self.root / row['path']
        if not source.resolve().is_relative_to(self.root):
            raise IaCError('iac_catalog_path')
        if (execution_tree(self.root,row) != handle['origin']['moduleRevision']
                or 'sha256:'+hashlib.sha256((source/'.terraform.lock.hcl').read_bytes()).hexdigest() != handle['origin']['providerLockDigest']):
            raise IaCError('iac_module_binding')
        owner = digest(handle)
        if existing.get('providerIdentity') != handle['providerIdentity']:
            raise IaCError('iac_provider_identity')
        previous = [entry for entry in store.entries() if entry['payload']['stateHandle'] == handle]
        if operation in ('destroy','unlock') and not previous:
            raise IaCError('iac_historical_handle_required')
        if existing.get('exists'):
            if not previous or existing.get('ownerDigest') != owner:
                raise IaCError('iac_unowned_existing_resource')
        elif operation not in ('destroy','unlock') and handle['ownership'] != 'managed':
            raise IaCError('iac_adoption_prerequisite')
        from credential_context import execution_credentials
        credentials,backend_credentials=execution_credentials(handle,credentials)
        credential_names = {'AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY','AWS_SESSION_TOKEN','AWS_REGION',
            'AWS_DEFAULT_REGION','GOOGLE_APPLICATION_CREDENTIALS','GOOGLE_PROJECT',
            'ARM_CLIENT_ID','ARM_TENANT_ID','ARM_SUBSCRIPTION_ID','ARM_USE_OIDC','ARM_OIDC_TOKEN',
            'ARM_OIDC_TOKEN_FILE_PATH','ARM_USE_AZUREAD','ARM_USE_CLI','ARM_USE_MSI','KUBECONFIG','TF_VAR_package_read_sas',
            'CLOUDSDK_AUTH_CREDENTIAL_FILE_OVERRIDE','AZURE_CONFIG_DIR','PATH'}
        if not isinstance(credentials,dict) or any(k not in credential_names or not isinstance(v,str) for k,v in credentials.items()):
            raise IaCError('iac_environment_override')
        # Durable full handle, including origin/backend/native lock address,
        # exists and was actor-verified by fresh API read-back before INIT.
        store.reserve(handle,resource_claims)
        env = {'PATH':os.environ.get('PATH',''),
               'TF_IN_AUTOMATION':'true','TF_INPUT':'false','TG_NON_INTERACTIVE':'true',
               'TG_TF_PATH':self.tofu, **credentials}
        with tempfile.TemporaryDirectory(prefix='cloudopsworks-iac-') as directory:
            work = Path(directory);work.chmod(0o700)
            # No implicit developer/runner cloud credentials or CLI caches. Only
            # explicit protected credentials above may reach provider/backends.
            home=work/'private-home';home.mkdir(mode=0o700)
            empty=home/'empty';empty.write_text('');empty.chmod(0o600)
            env.update(HOME=str(home), AWS_EC2_METADATA_DISABLED='true',
                AWS_SHARED_CREDENTIALS_FILE=str(empty), AWS_CONFIG_FILE=str(empty),
                AZURE_CONFIG_DIR=str(home/'azure'), CLOUDSDK_CONFIG=str(home/'gcloud'))
            for name in row['files']:
                target = work/name;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(source/name,target);target.chmod(0o600)
            backend_values=native_backend(handle)
            backend_values['terraform']['backend'][handle['backend']['kind']].update(backend_credentials)
            (work/'backend.tf.json').write_bytes(canonical_bytes(backend_values))
            (work/'values.auto.tfvars.json').write_bytes(canonical_bytes(values))
            for name in ('backend.tf.json','values.auto.tfvars.json'):
                (work/name).chmod(0o600)
            version = _run(self.executor,[self.tofu,'version','-json'],cwd=work,env=env)
            try:
                if json.loads(version.stdout)['terraform_version'] != self.catalog['tools']['opentofu']:
                    raise IaCError('iac_tool_version')
            except (ValueError,KeyError,TypeError):
                raise IaCError('iac_tool_version') from None
            tg = _run(self.executor,[self.terragrunt,'--version'],cwd=work,env=env)
            if not re.fullmatch(r'terragrunt version v?'+re.escape(self.catalog['tools']['terragrunt'])+r'\s*',tg.stdout):
                raise IaCError('iac_tool_version')
            def run(args,codes=(0,)):
                return _run(self.executor,_shared.command(args,tool=self.terragrunt,working_directory=work),cwd=work,env=env,codes=codes)
            run(['init','-input=false','-lockfile=readonly'])
            selected=run(['workspace','select',handle['backend']['workspace']],codes=(0,1))
            if selected.returncode:
                fresh=(not previous and not existing.get('exists') and handle['ownership']=='managed'
                       and operation in ('apply','preview'))
                if not fresh or handle['backend']['workspace']=='default':
                    raise IaCError('iac_historical_workspace_missing')
                run(['workspace','new',handle['backend']['workspace']])
            pulled=run(['state','pull'],codes=(0,1))
            prior_addresses=set()
            if pulled.returncode==0:
                try:
                    state=json.loads(pulled.stdout)
                    if expected_state_digest is not None and digest(state)!=expected_state_digest:
                        raise IaCError('iac_private_state_changed_since_preflight')
                    if not isinstance(state,dict) or state.get('version')!=4:
                        raise ValueError('invalid state')
                    for resource in state.get('resources',[]):
                        if resource.get('mode')=='data': continue
                        if resource.get('mode')!='managed' or resource.get('module'):
                            raise ValueError('unsupported module state')
                        prefix=resource['type']+'.'+resource['name']
                        for instance in resource['instances']:
                            address=prefix
                            if 'index_key' in instance:
                                address+='['+canonical_bytes(instance['index_key']).decode()+']'
                            prior_addresses.add(address)
                except (ValueError,KeyError,TypeError):
                    raise IaCError('iac_state_invalid') from None
            elif existing.get('exists') or expected_state_digest is not None:
                raise IaCError('iac_state_missing_for_existing')
            if operation == 'unlock':
                run(['force-unlock','-force',plan['lockId']])
                return {'phase':'unlock','counts':{},'stateHandleDigest':owner}
            args=['plan','-input=false','-lock-timeout=60s','-detailed-exitcode','-out=operation.tfplan']
            if operation == 'destroy': args.append('-destroy')
            result=run(args,codes=(0,2))
            inspected=run(['show','-json','operation.tfplan'])
            try: saved=json.loads(inspected.stdout)
            except ValueError: raise IaCError('iac_plan_invalid') from None
            counts=verify_saved_plan(saved,operation=operation,addresses=row['ownedResourceAddresses'],
                owner_digest=owner,previously_owned=prior_addresses,replacements=row.get('replaceResourceAddresses',()),apply_deletes=row.get('applyDeleteResourceAddresses',()))
            verify_appengine_plan(saved,handle,previously_owned=prior_addresses)
            if result.returncode == 2:
                if before_apply is not None:
                    if not callable(before_apply):raise IaCError('iac_pre_submit_guard_invalid')
                    before_apply()
                run(['apply','-input=false','operation.tfplan'])
            completed={'phase':operation,'counts':counts,'stateHandleDigest':owner}
            if operation in ('apply','preview') and verify_ready is not None:
                output=run(['output','-json'])
                try:
                    outputs=json.loads(output.stdout)
                    if not isinstance(outputs,dict) or any(not isinstance(v,dict) or v.get('sensitive') is not False or 'value' not in v for v in outputs.values()):
                        raise ValueError('invalid output')
                except (ValueError,TypeError):
                    raise IaCError('iac_output_invalid') from None
                normalized={k:v['value'] for k,v in outputs.items()}
                if verify_applied is not None:
                    if not callable(verify_applied):raise IaCError('iac_post_apply_guard_invalid')
                    pulled=run(['state','pull'])
                    try:private_state=json.loads(pulled.stdout)
                    except ValueError:raise IaCError('iac_state_invalid') from None
                    verify_applied(normalized,private_state,saved)
                completed['resourceUrl']=verify_ready(normalized)
            return completed
