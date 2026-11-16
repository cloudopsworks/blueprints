"""Generate fixed root values from verified records and immutable payload bytes.

No source YAML/HCL, arbitrary application environment, credentials, hooks or
package URI is accepted. Root metadata only projects existing authoritative
wire data; it is pinned with the trusted module tree, not operator config.
"""
from __future__ import annotations
import copy
import json
import mimetypes
from pathlib import Path
import re
import tarfile
import zipfile

from contracts import _artifact, _check, _pairs, _constant, canonical_bytes, digest, schema, validate_artifact
from operations import validate_operation


class ValuesError(ValueError):
    pass


def _project(value, fields):
    if value is None:return None
    result={}
    for field in fields:
        parts=field.split('.');cursor=value
        for key in parts:
            if not isinstance(cursor,dict) or key not in cursor:
                break
            cursor=cursor[key]
        else:
            target=result
            for key in parts[:-1]:target=target.setdefault(key,{})
            target[parts[-1]]=copy.deepcopy(cursor)
    return result


def render_values(plan, metadata, artifact, *, work, artifact_path=None,
                  image_reference=None, package_handler=None, static_marker=None,
                  chart_path=None, kubeconfig_path=None, readiness_seconds=None, resolved_api=None, preview_isolation=None, preview_options=None):
    validate_operation(plan)
    _check(artifact,schema()["$defs"]["Artifact"],"$.artifact")
    _artifact(artifact,repository=plan["stateHandle"]["origin"]["repository"])
    if plan['operation'] not in ('apply','preview') or plan['inputs'] is None:
        raise ValuesError('iac_values_operation')
    work=Path(work)
    if work.is_symlink() or not work.is_dir() or any(work.iterdir()) or work.stat().st_mode & 0o077:
        raise ValuesError('iac_values_private_workspace')
    work=work.resolve()
    if plan['stateHandle']['moduleId'] not in [metadata.get('moduleId'),*metadata.get('acceptedModuleIds',[])]:
        raise ValuesError('iac_values_module')
    generated={'digest':artifact['digest'],'format':{'openapi-json':'json','openapi-yaml':'yaml'}.get(artifact['format'],artifact['format']),'path':None,'imageReference':None,'files':[]}
    environment_only=(plan['operation']=='preview' and plan['stateHandle']['scope']=='preview-environment'
                      and 'artifact' not in metadata['variables'])
    if environment_only:
        pass # Namespace/policy/probes consume no application artifact or payload.
    elif artifact['format']=='oci':
        reference=image_reference or artifact.get('location',{}).get('reference')
        if (not isinstance(reference,str) or not reference.endswith('@'+artifact['digest'])
                or re.search(r'[\s\x00-\x1f?#]',reference) or '://' in reference):
            raise ValuesError('iac_values_immutable_image')
        generated['imageReference']=reference
    else:
        if artifact_path is None:
            raise ValuesError('iac_values_payload_missing')
        source=Path(artifact_path)
        if source.is_symlink() or not source.is_file():
            raise ValuesError('iac_values_payload_file')
        target=work/('payload-'+artifact['digest'][7:]+'.'+{'zip':'zip','tar.gz':'tar.gz','openapi-json':'json','openapi-yaml':'yaml'}[artifact['format']])
        # Snapshot before validation; a mutable source path cannot race extraction.
        with source.open('rb') as incoming,target.open('xb') as output:
            total=0
            while chunk:=incoming.read(1024*1024):
                total+=len(chunk)
                if total>artifact['sizeBytes']:
                    raise ValuesError('iac_values_payload_size')
                output.write(chunk)
        target.chmod(0o600)
        validate_artifact(target,artifact)
        generated['path']=str(target)
        if plan['inputs']['resource']['kind']=='aws.beanstalk':
            stack=plan['inputs']['configuration'].get('iac',{}).get('solutionStackName','')
            with zipfile.ZipFile(target) as archive:
                entries={entry.filename for entry in archive.infolist() if not entry.is_dir()}
                if 'Docker' in stack:
                    # Existing native Dockerrun v1 configuration is data only:
                    # never permit an on-host Dockerfile build or source hooks.
                    if entries!={'Dockerrun.aws.json'}:
                        raise ValuesError('iac_values_dockerrun_payload')
                    raw=archive.read('Dockerrun.aws.json')
                    if len(raw)>65536:raise ValuesError('iac_values_dockerrun_bound')
                    try:document=json.loads(raw,object_pairs_hook=_pairs,parse_constant=_constant)
                    except (ValueError,TypeError):raise ValuesError('iac_values_dockerrun_json') from None
                    if (not isinstance(document,dict) or set(document)!={'AWSEBDockerrunVersion','Image','Ports'}
                            or document['AWSEBDockerrunVersion']!='1'
                            or not isinstance(document['Image'],dict)
                            or set(document['Image'])-{'Name','Update'} or 'Name' not in document['Image']
                            or document['Image'].get('Update','true') not in ('true','false')
                            or not isinstance(document['Image']['Name'],str)
                            or not re.fullmatch(r'[a-z0-9][a-z0-9.:-]*/[a-z0-9._/-]+@sha256:[0-9a-f]{64}',document['Image']['Name'])
                            or not isinstance(document['Ports'],list) or len(document['Ports'])!=1
                            or not isinstance(document['Ports'][0],dict) or set(document['Ports'][0])!={'ContainerPort'}
                            or not isinstance(document['Ports'][0]['ContainerPort'],str)
                            or not re.fullmatch(r'[1-9][0-9]{0,4}',document['Ports'][0]['ContainerPort'])
                            or int(document['Ports'][0]['ContainerPort'])>65535):
                        raise ValuesError('iac_values_dockerrun_immutable')
                    generated['imageReference']=document['Image']['Name']
                elif 'Dockerrun.aws.json' in entries or 'Dockerfile' in entries:
                    raise ValuesError('iac_values_dockerrun_stack')
        if artifact['kind']=='static':
            directory=work/'objects';directory.mkdir(mode=0o700)
            if artifact['format']=='zip':
                with zipfile.ZipFile(target) as archive:archive.extractall(directory)
            else:
                with tarfile.open(target,'r:gz') as archive:archive.extractall(directory,filter='data')
            if (directory/'.cloudopsworks-release.json').exists():
                raise ValuesError('iac_values_reserved_marker')
            if (not isinstance(static_marker,dict) or set(static_marker)!={'artifactDigest','releaseVersion','idempotencyKey'}
                    or static_marker['artifactDigest']!=artifact['digest']
                    or not all(isinstance(v,str) for v in static_marker.values())
                    or not re.fullmatch(r'sha256:[0-9a-f]{64}',static_marker['idempotencyKey'])):
                raise ValuesError('iac_values_static_marker')
            (directory/'.cloudopsworks-release.json').write_bytes(canonical_bytes(static_marker))
            for path in sorted(directory.rglob('*')):
                if path.is_file():
                    path.chmod(0o600)
                    generated['files'].append({'path':str(path),'key':path.relative_to(directory).as_posix(),
                        'contentType':mimetypes.guess_type(path.name)[0] or 'application/octet-stream'})
    inputs=plan['inputs']
    if resolved_api is not None:
        # Derived only by the trusted private-state/native-identity verifier.
        # Never read API names/descriptions from the OpenAPI document.
        if (inputs['resource']['kind']!='aws.apigateway-rest'
                or not inputs['resource'].get('restApiId')
                or not isinstance(resolved_api,dict) or set(resolved_api)!={'name','description'}
                or not isinstance(resolved_api['name'],str) or not 1<=len(resolved_api['name'])<=1024
                or not isinstance(resolved_api['description'],str) or len(resolved_api['description'])>1024
                or any(ord(c)<32 or ord(c)==127 for value in resolved_api.values() for c in value)):
            raise ValuesError('iac_values_resolved_api')
    preview_fields={'probeImage','controlNamespace','ingressNamespace','ingressNamespaceSelector',
        'ingressPodSelector','dnsNamespaceSelector','dnsPodSelector'}
    if preview_isolation is not None:
        if (plan['operation']!='preview' or plan['stateHandle']['scope']!='preview-environment'
                or not isinstance(preview_isolation,dict) or set(preview_isolation)!=preview_fields):
            raise ValuesError('iac_values_preview_isolation')
        for name,value in preview_isolation.items():
            if name.endswith('Selector'):
                if not isinstance(value,dict) or not value or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in value.items()):
                    raise ValuesError('iac_values_preview_selector')
            elif not isinstance(value,str) or not value or any(ord(c)<32 for c in value):
                raise ValuesError('iac_values_preview_isolation')
        if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',preview_isolation['probeImage']):
            raise ValuesError('iac_values_preview_probe_image')
    if preview_options is not None:
        if (plan['operation']!='preview' or plan['stateHandle']['scope']!='preview-component'
                or not isinstance(preview_options,dict) or set(preview_options)!={'host','ingressClass'}
                or not all(isinstance(v,str) and re.fullmatch(r'[a-z0-9][a-z0-9.-]{0,252}',v) for v in preview_options.values())):
            raise ValuesError('iac_values_preview_options')
    values={'resource':inputs['resource'],'configuration':inputs['configuration'],'workload':inputs['workload'],
            'artifact':generated,'owner_digest':digest(plan['stateHandle']),'package_handler':package_handler,
            'release_name':plan['stateHandle']['componentId'],'chart_path':str(chart_path) if chart_path else None,
            'kubeconfig_path':str(kubeconfig_path) if kubeconfig_path else None,'readiness_seconds':readiness_seconds,'resolved_api':resolved_api,
            'namespace':plan['stateHandle']['resourceIdentity'].get('namespace'),
            'repository_id':plan['stateHandle']['origin']['repository']['id'],
            'pr_number':plan['stateHandle']['prNumber'],'target_id':plan['stateHandle']['targetId'],
            'isolation':preview_isolation,'preview_options':preview_options}
    result={}
    for name,fields in metadata['variables'].items():
        if name not in values:
            raise ValuesError('iac_values_unknown_projection')
        result[name]=_project(values[name],fields) if fields else copy.deepcopy(values[name])
    return result


def recovery_values(inputs, metadata, handle, private_state, *, work, package_handler=None,
                    chart_path=None, kubeconfig_path=None, resolved_api=None, preview_isolation=None):
    """Private destroy-only evaluation scaffolding, never a release Artifact.

    Actual Go regenerates inputs from independently proved historical YAML.
    A placeholder's bytes describe no deployed artifact: only pure saved-plan
    deletes of exact private-owned addresses may execute. No source is fetched,
    no immutable payload is republished, and no scaffold crosses a public wire.
    """
    if not isinstance(inputs,dict) or set(inputs)!={'resource','configuration','workload'}:
        raise ValuesError('iac_recovery_inputs')
    if inputs['resource']!=handle['resourceIdentity'] or private_state.get('version')!=4:
        raise ValuesError('iac_recovery_owner')
    work=Path(work).resolve()
    if not work.is_dir() or any(work.iterdir()) or work.stat().st_mode&0o077:
        raise ValuesError('iac_recovery_workspace')
    if handle['scope']=='preview-environment':
        # Only immutable historical policy/native-parent projection is accepted
        # from the independent recovery factory. No application artifact exists
        # or is fabricated for namespace/policy/probe teardown.
        fields={'probeImage','controlNamespace','ingressNamespace','ingressNamespaceSelector',
            'ingressPodSelector','dnsNamespaceSelector','dnsPodSelector'}
        if (handle['prNumber'] is None or 'artifact' in metadata['variables']
                or not isinstance(preview_isolation,dict) or set(preview_isolation)!=fields):
            raise ValuesError('iac_recovery_preview_isolation')
        for name,value in preview_isolation.items():
            if name.endswith('Selector'):
                if not isinstance(value,dict) or not value or any(not isinstance(k,str) or not k or not isinstance(v,str) or not v for k,v in value.items()):
                    raise ValuesError('iac_recovery_preview_isolation')
            elif not isinstance(value,str) or not value or any(ord(c)<32 for c in value):
                raise ValuesError('iac_recovery_preview_isolation')
        if not re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',preview_isolation['probeImage']):
            raise ValuesError('iac_recovery_preview_isolation')
        values={'resource':inputs['resource'],'configuration':inputs['configuration'],'workload':inputs['workload'],
            'owner_digest':digest(handle),'namespace':handle['resourceIdentity']['namespace'],
            'repository_id':handle['origin']['repository']['id'],'pr_number':handle['prNumber'],
            'target_id':handle['targetId'],'kubeconfig_path':str(kubeconfig_path) if kubeconfig_path else None,
            'isolation':preview_isolation}
        if any(name not in values for name in metadata['variables']):
            raise ValuesError('iac_recovery_projection')
        return {name:_project(values[name],parts) if parts else copy.deepcopy(values[name])
            for name,parts in metadata['variables'].items()}
    if preview_isolation is not None:raise ValuesError('iac_recovery_preview_scope')
    images=set()
    def image_values(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('image','image_uri','docker_image_name') and isinstance(item,str) and re.fullmatch(r'[^\s]+@sha256:[0-9a-f]{64}',item):images.add(item)
                image_values(item)
        elif isinstance(value,list):
            for item in value:image_values(item)
    image_values(private_state)
    if len(images)>1:raise ValuesError('iac_recovery_image_ambiguity')
    image=next(iter(images),None)
    api=handle['resourceIdentity']['kind'] in ('aws.apigateway-rest','gcp.apigateway','azure.apim')
    placeholder=work/('evaluation.json' if api else 'evaluation.zip')
    if api:
        placeholder.write_bytes(canonical_bytes({'openapi':'3.0.3','info':{'title':'private-destroy-evaluation','version':'0.0.0'},'paths':{}}))
    else:
        with zipfile.ZipFile(placeholder,'w'):pass
    placeholder.chmod(0o600)
    import hashlib
    oci=bool(image) and handle['moduleId']!='aws-beanstalk'
    generated={'digest':('sha256:'+image.rsplit('@sha256:',1)[1] if oci else 'sha256:'+hashlib.sha256(placeholder.read_bytes()).hexdigest()),
        'format':'oci' if oci else 'json' if api else 'zip','path':str(placeholder),'imageReference':image,'files':[]}
    values={'resource':inputs['resource'],'configuration':inputs['configuration'],'workload':inputs['workload'],
        'artifact':generated,'owner_digest':digest(handle),'package_handler':package_handler,
        'release_name':handle['componentId'],'chart_path':str(chart_path) if chart_path else None,
        'kubeconfig_path':str(kubeconfig_path) if kubeconfig_path else None,'readiness_seconds':600,
        'resolved_api':resolved_api,'preview_options':None}
    result={}
    for name,fields in metadata['variables'].items():
        if name not in values:raise ValuesError('iac_recovery_projection')
        result[name]=_project(values[name],fields) if fields else copy.deepcopy(values[name])
    return result
