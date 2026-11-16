"""The only schema-v2 normal workload mutation boundary.

The authorization callback is trusted orchestration code, never source data. It
must independently regenerate the complete operation from immutable API config,
verify host/caller and current scanner policy, and return a verified state store.
A schema-valid artifact/operation is deliberately insufficient authorization.
"""
from __future__ import annotations
import json
from pathlib import Path
import tempfile

from contracts import ContractError
from iac_values import render_values
from iac import execution_tree
from operations import validate_operation
from providers import common as c


def apply(request, executor, resolved, context, payload, directory, image):
    authorize=context.get('iac_authorize')
    c.require(callable(authorize),'iac-authorization-required','independent protected operation authorization is required')
    bound=authorize(request,resolved)
    c.require(isinstance(bound,dict) and set(bound)=={'plan','canonical','store','resourceClaims','existing','credentials','engine'},
              'iac-authorization-invalid','protected operation authorization is incomplete')
    plan=validate_operation(bound['plan'],canonical=bound['canonical'])
    from credential_context import execution_credentials
    provider_credentials,_=execution_credentials(plan['stateHandle'],bound['credentials'])
    handle=plan['stateHandle']
    c.require(plan['operation']=='apply' and handle['componentId']==request['componentId']
        and handle['targetId']==request['target']['id'] and handle['origin']['repository']==request['repository']
        and handle['providerIdentity']==resolved['providerIdentity'] and plan['inputs']['workload']==request['workload'],
        'iac-request-binding','authorized operation differs from requested workload')
    # Canonical authorization also binds all mutable target/package fields, the
    # intended artifact and CURRENT required gates; not merely this shape check.
    engine=bound['engine'];row=engine.catalog.get('modules',{}).get(handle['moduleId'])
    c.require(row is not None and row.get('activationBlocked') is False,'iac-capability-blocked','selected root is not activated')
    c.require(execution_tree(engine.root,row)==handle['origin']['moduleRevision'],'iac-module-binding','fixed root or chart bytes differ')
    root=engine.root/row['path']
    metadata=json.loads((root/'inputs.json').read_text())
    # Metadata is covered by the same immutable root tree checked by execute.
    c.require('inputs.json' in row['files'],'iac-root-metadata','root metadata is not pinned')
    if image:
        from providers.registry import materialize
        image=materialize(request,executor,context,image,lambda_resource=resolved.get('resource') if request['target']['kind']=='aws.lambda' else None)
    with tempfile.TemporaryDirectory(prefix='cloudopsworks-values-',dir=context['workDir']) as directory_name:
        work=Path(directory_name);work.chmod(0o700)
        values=render_values(plan,metadata,request['artifact'],work=work,artifact_path=payload,
            image_reference=image,package_handler=request['package'].get('entryPoint'),static_marker=json.loads(c.marker(request)),
            chart_path=engine.root/row['chartPath'] if row.get('chartPath') else None,
            kubeconfig_path=context.get('kubeconfigPath',provider_credentials.get('KUBECONFIG')),readiness_seconds=request['target']['readiness']['deadlineSeconds'],
            resolved_api=resolved.get('verifiedApiConfiguration'))
        def ready(outputs):
            from providers.readiness import verify
            return verify(request,executor,dict(context,iacOwnerDigest=plan['stateHandleDigest'],kubeconfigPath=context.get('kubeconfigPath',provider_credentials.get('KUBECONFIG'))),outputs,image=image,directory=directory)
        verify_applied=None
        if request['target']['kind']=='aws.apigateway-rest' and not request['target'].get('restApiId'):
            def verify_applied(outputs,state,saved):
                owned=outputs.get('owned',{});api_id=owned.get('restApiId')
                bind=context.get('bind_created_rest_api')
                c.require(callable(bind),'iac-created-api-binding','trusted generated API binding is required')
                def creation(exact_handle,exact_id):
                    c.require(exact_handle==handle and exact_id==api_id,'iac-created-api-binding','generated API owner differs')
                    resources=[r for r in state.get('resources',[]) if r.get('mode')=='managed'
                        and r.get('type')=='aws_api_gateway_rest_api' and r.get('name')=='component' and not r.get('module')]
                    c.require(state.get('version')==4 and len(resources)==1 and len(resources[0].get('instances',[]))==1,
                        'iac-created-api-state','generated API is absent from exact private owned state')
                    attrs=resources[0]['instances'][0].get('attributes',{})
                    c.require(attrs.get('id')==api_id and attrs.get('name')==request['target']['apiName']
                        and attrs.get('tags',{}).get('cloudopsworks-owner')==plan['stateHandleDigest'],
                        'iac-created-api-state','generated API private owner or name differs')
                    from providers.aws import cli
                    native=cli(executor,request['target'],'apigateway','get-rest-api','--rest-api-id',api_id)
                    c.require(native.get('id')==api_id and native.get('name')==attrs['name']
                        and native.get('tags',{}).get('cloudopsworks-owner')==plan['stateHandleDigest'],
                        'iac-created-api-native','generated API native owner differs')
                    changes=[r for r in saved.get('resource_changes',[]) if r.get('address')=='aws_api_gateway_rest_api.component']
                    c.require(len(changes)==1 and changes[0]['change']['actions'] in (['create'],['update'],['no-op']),
                        'iac-created-api-plan','generated API creation has no exact reviewed saved operation')
                    return True
                bind(handle,api_id,verify_creation=creation)
        completed=engine.execute(plan,canonical=bound['canonical'],store=bound['store'],
            resource_claims=bound['resourceClaims'],existing=bound['existing'],values=values,
            credentials=bound['credentials'],verify_ready=ready,
            expected_state_digest=context.get('privateStateDigests',{}).get((request['target']['id'],request['componentId'])),
            before_apply=context.get('before_apply'),verify_applied=verify_applied)
    return completed['resourceUrl']
