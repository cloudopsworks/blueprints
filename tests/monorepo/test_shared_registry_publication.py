"""Historical rejected-helper characterization plus actual legacy-action contracts.

Helper imports remain only while rejected runtime consumers still reference it.
New composite acceptance lives in actions/container-publication.test.mjs.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[2]
HELPER=ROOT/'cd/deploy/container/publication.py'
spec=importlib.util.spec_from_file_location('shared_publication_test',HELPER)
publication=importlib.util.module_from_spec(spec);spec.loader.exec_module(publication)
DIGEST='sha256:'+'b'*64
REPOSITORY='registry.example/owner/project'
SOURCE='ghcr.io/owner/project@'+DIGEST
# Frozen original default action command bodies, before shared extraction.
CRANE='''echo "::group::Push Docker image from tar using Crane"
TAG=$(head -1 docker-tags.list)
crane push docker-image.tar "${STEPS_DOCKER_REGISTRY_RESULT}/${INPUTS_PROJECT_OWNER}/${INPUTS_PROJECT_KEY}:$TAG"
echo "::notice::Pushed Docker image to ${STEPS_DOCKER_REGISTRY_RESULT}/${INPUTS_PROJECT_OWNER}/${INPUTS_PROJECT_KEY}:$TAG"
for atag in $(cat docker-tags.list); do
  if [ "$atag" != "$TAG" ]; then
    crane tag "${STEPS_DOCKER_REGISTRY_RESULT}/${INPUTS_PROJECT_OWNER}/${INPUTS_PROJECT_KEY}:$TAG" $atag
    echo "::notice::Tagged Docker image to ${STEPS_DOCKER_REGISTRY_RESULT}/${INPUTS_PROJECT_OWNER}/${INPUTS_PROJECT_KEY}:$atag"
  fi
done
echo "::endgroup::"
'''
DOCKER='''docker image load --input docker-image.tar
docker image push --all-tags "${STEPS_DOCKER_REGISTRY_RESULT}/${INPUTS_PROJECT_OWNER}/${INPUTS_PROJECT_KEY}"
'''


class SharedRegistryTests(unittest.TestCase):
    def test_legacy_actual_helper_commands_notices_and_auth_inheritance_match_defaults(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);log=root/'commands.jsonl'
            stub='#!'+sys.executable+'''\nimport json,os,sys
with open(os.environ['COMMAND_LOG'],'a') as stream:
 stream.write(json.dumps({'argv':[os.path.basename(sys.argv[0]),*sys.argv[1:]],'config':os.environ.get('DOCKER_CONFIG')})+'\\n')
'''
            for binary in ('crane','docker'):
                path=root/binary;path.write_text(stub);path.chmod(0o700)
            env={**os.environ,'PATH':str(root)+os.pathsep+os.defpath,'COMMAND_LOG':str(log),
                 'STEPS_DOCKER_REGISTRY_RESULT':'registry.example','INPUTS_PROJECT_OWNER':'owner',
                 'INPUTS_PROJECT_KEY':'project','DOCKER_CONFIG':str(root/'existing-login-config')}
            for transport,script in [('crane',CRANE),('docker',DOCKER)]:
                for tags in ('v1.0.0\nlatest\nstable\nv1.0.0\n', 'v1\n\tlatest   stable\nlatest\n','v1\r\nlatest\r\n',''):
                    (root/'docker-tags.list').write_bytes(tags.encode())
                    results=[]
                    for command in (['bash','-e','-c',script],[sys.executable,str(HELPER),'legacy-'+transport]):
                        log.write_text('')
                        process=subprocess.run(command,cwd=root,env=env,text=True,capture_output=True)
                        self.assertEqual(process.returncode,0,process.stderr)
                        results.append((process.stdout,[json.loads(line) for line in log.read_text().splitlines()]))
                    with self.subTest(transport=transport,tags=tags):self.assertEqual(results[0],results[1])
    def test_action_defaults_keep_legacy_credentials_and_use_native_inline_transports(self):
        action=(HELPER.parent/'action.yml').read_text()
        self.assertNotIn('publication.py',action)
        self.assertIn("steps.docker_daemon.outputs.docker_daemon == 'true'",action)
        self.assertIn("steps.docker_daemon.outputs.docker_daemon != 'true'",action)
        for value in ('docker/login-action@v4','aws-actions/configure-aws-credentials@v6','actions/download-artifact@v7'):
            self.assertIn(value,action)
        from test_legacy_action_contracts import read_yaml
        current=read_yaml(HELPER.parent/'action.yml')
        self.assertEqual(current['inputs']['component-mode']['default'],'false')
        native={step.get('id'):step for step in current['runs']['steps']}
        for identifier in ('legacy-docker','legacy-crane'):
            self.assertEqual(native[identifier]['uses'],'actions/github-script@v9')
            self.assertIn("inputs.component-mode != 'true'",native[identifier]['if'])
        self.assertIn("exec.getExecOutput('docker', ['image', 'load'",native['legacy-docker']['with']['script'])
        self.assertIn("exec.getExecOutput('crane', ['push'",native['legacy-crane']['with']['script'])
    def test_real_immutable_primitive_owns_copy_and_both_digest_readbacks(self):
        calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            return DIGEST if argv[:2]==['skopeo','inspect'] else ''
        image=publication.publish(run,transport='skopeo',source=SOURCE,repository=REPOSITORY,
                                  tags=['sha256-'+'b'*64],authfile=Path('/private/auth'),expected_digest=DIGEST)
        self.assertEqual(image,REPOSITORY+'@'+DIGEST)
        self.assertEqual([argv[:2] for argv,_ in calls],[['skopeo','inspect'],['skopeo','copy'],['skopeo','inspect']])
        self.assertEqual(calls[1][0],['skopeo','copy','--all','--preserve-digests','--authfile','/private/auth','docker://'+SOURCE,'docker://'+REPOSITORY+':sha256-'+'b'*64])
    def test_rewritten_or_mutable_digest_and_upload_denial_never_succeed(self):
        for failure in ('source','destination','denied','invalid'):
            calls=[]
            def run(argv,**kwargs):
                calls.append(argv)
                if failure=='denied' and argv[:2]==['skopeo','copy']:raise RuntimeError('recorded upload denial')
                if argv[:2]==['skopeo','inspect']:
                    if failure=='invalid':return 'not-a-digest'
                    if failure=='source' or (failure=='destination' and len(calls)==3):return 'sha256:'+'a'*64
                    return DIGEST
                return ''
            with self.subTest(failure=failure),self.assertRaises((publication.PublicationError,RuntimeError)):
                publication.publish(run,transport='skopeo',source=SOURCE,repository=REPOSITORY,
                    tags=['sha256-'+'b'*64],authfile='/private/auth',expected_digest=DIGEST)
            if failure in ('source','invalid'):self.assertEqual(len(calls),1)
        with self.assertRaises(publication.PublicationError):
            publication.publish(lambda *a,**kw:self.fail('must fail before command'),transport='skopeo',
                source='ghcr.io/owner/project:latest',repository=REPOSITORY,tags=['sha256-'+'b'*64],authfile='/private/auth',expected_digest=DIGEST)
    def test_rejected_runtime_consumer_still_requires_helper_until_migration(self):
        from test_providers_registry import RegistryFake, RegistryTests, ECR
        from providers import registry
        original=registry._publication.publish
        executions=[]
        def observed(*args,**kwargs):
            executions.append(kwargs['transport']);return original(*args,**kwargs)
        r=RegistryTests().fixture('aws.lambda');ex=RegistryFake(r)
        with tempfile.TemporaryDirectory() as root,patch.object(registry._publication,'publish',side_effect=observed):
            registry.materialize(r,ex,{'workDir':root,'expectedIdentity':'123456789012'},SOURCE,
                lambda_resource={'Code':{'ResolvedImageUri':ECR+'@'+DIGEST}})
        self.assertEqual(executions,['skopeo'])
        self.assertEqual(Path(registry._publication.__file__).resolve(),HELPER.resolve())


if __name__=='__main__':unittest.main()
