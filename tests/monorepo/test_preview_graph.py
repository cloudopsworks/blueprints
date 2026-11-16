"""Static reusable holder/auth graph proof; no claim about hosted scheduling."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'cd/monorepo/runtime'))
from authorization import preview_phase_name


def yaml(path):
    # Existing system Ruby parser only for authored workflow/composite tests;
    # runtime configuration resolution remains exclusively the Go CLI.
    result=subprocess.run(['ruby','-ryaml','-rjson','-e','puts JSON.generate(YAML.load_file(ARGV[0]))',str(path)],capture_output=True,text=True)
    if result.returncode:raise AssertionError(result.stderr)
    return json.loads(result.stdout)


class PreviewGraphTests(unittest.TestCase):
    def test_one_reusable_call_holder_has_exact_pr_target_group_no_outer_group(self):
        flow=yaml(ROOT/'.github/workflows/monorepo-preview.yml')
        self.assertNotIn('concurrency',flow)
        holder=flow['jobs']['target']
        self.assertIn('uses',holder);self.assertNotIn('runs-on',holder);self.assertNotIn('environment',holder)
        self.assertEqual(holder['uses'],'./.github/workflows/monorepo-preview-target.yml')
        self.assertEqual(holder['concurrency'],{'group':'monorepo-preview-${{ github.repository_id }}-${{ matrix.pr }}-${{ matrix.id }}','cancel-in-progress':False})
        self.assertEqual(flow['jobs']['discover']['permissions']['deployments'],'read')
        self.assertNotIn('id-token',flow['jobs']['discover']['permissions'])
        close=yaml(ROOT/'.github/workflows/monorepo-pr-close.yml')
        self.assertNotIn('concurrency',close)
        self.assertEqual(close['jobs']['lifecycle']['needs'],'preview')
        self.assertEqual(close['jobs']['lifecycle']['uses'],'./.github/workflows/monorepo-closure.yml')

    def test_exact_phase_names_match_shared_authority_fixture(self):
        flow=yaml(ROOT/'.github/workflows/monorepo-preview-target.yml')
        for phase in ('root','component','cleanup','destroy','scan','component-scan'):
            job=flow['jobs'][phase]
            expected=preview_phase_name('pr-build.yml','dev-run',phase,'api' if phase in ('component','cleanup','component-scan') else None)
            actual=job['name'].replace('${{ inputs.target }}','dev-run').replace('${{ matrix.component }}','api')
            self.assertEqual('preview / monorepo-preview-dev-run / '+actual,expected)
        for name in ('component','cleanup','retire'):
            self.assertEqual(flow['jobs'][name]['strategy']['max-parallel'],1)
            self.assertTrue(flow['jobs'][name]['strategy']['fail-fast'])
        for name in ('root','component','cleanup','retire','destroy','absence','readiness'):
            job=flow['jobs'][name]
            self.assertEqual(job['environment'],'${{ inputs.environment }}')
            self.assertEqual(job['permissions']['id-token'],'write')
            self.assertEqual(job['env']['DEPLOYMENT_STATE_CONF'],'${{ vars.DEPLOYMENT_STATE_CONF || secrets.DEPLOYMENT_STATE_CONF }}')
            self.assertNotIn('concurrency',job)
        self.assertIn('always()',flow['jobs']['cleanup']['if'])
        self.assertIn('failure-cleanup',flow['jobs']['cleanup']['if'])
        self.assertNotIn("needs.root.result == 'failure'",flow['jobs']['cleanup']['if'])
        self.assertIn('cleanup',flow['jobs']['destroy']['needs'])

    def test_closed_current_state_admitted_before_source_scan_and_auth(self):
        flow=yaml(ROOT/'.github/workflows/monorepo-preview-target.yml')
        steps=flow['jobs']['admit']['steps']
        self.assertFalse(any('auth' in step.get('uses','') or step.get('uses','').startswith('actions/download') for step in steps))
        self.assertTrue(all(step.get('with',{}).get('checkout_source')=='false' for step in steps if 'cd/checkout@' in step.get('uses','')))
        self.assertEqual(flow['jobs']['scan-context']['if'],"needs.admit.outputs.phase == 'open'")
        self.assertEqual(flow['jobs']['component-scan']['if'],"needs.admit.outputs.phase == 'open'")
        source=(ROOT/'cd/monorepo/runtime/preview_entry.py').read_text()
        self.assertIn("if route['current']['state']=='closed':",source)
        self.assertIn('prepare_preview_closure',source)
        self.assertIn('require_children_empty(github,route,target,ctrl._handles(),root',source)

    def test_composite_three_private_captures_after_selection_and_source_free_tools(self):
        action=yaml(ROOT/'cd/monorepo/preview-phase/action.yml')
        self.assertEqual(action['runs']['using'],'composite')
        steps=action['runs']['steps'];auths=[(i,s) for i,s in enumerate(steps) if s.get('uses')=='./bp/cd/monorepo/auth']
        self.assertEqual([s['with']['context-name'] for _,s in auths],['workload','backend','root-backend'])
        first=auths[0][0]
        self.assertEqual(steps[0]['id'],'selected')
        self.assertIn('configure --phase',steps[0]['run'])
        self.assertTrue(all(i<first for i,s in enumerate(steps) if s.get('uses') in ('./bp/cd/monorepo/tools','./bp/cd/deploy/common/iac')))
        self.assertTrue(all(s['with']['install-tools']=='false' for _,s in auths))
        self.assertIn('root-same-workload',auths[2][1]['if']);self.assertIn('root-same-backend',auths[2][1]['if'])
        self.assertFalse(any('upload' in s.get('uses','') or 'download' in s.get('uses','') for s in steps))

    @unittest.skipUnless(shutil.which('actionlint'),'actionlint installed for authored workflow validation')
    def test_real_actionlint_preview_workflows(self):
        names=['monorepo-preview.yml','monorepo-preview-target.yml']
        if (ROOT/'.github/workflows/monorepo-closure.yml').exists():names.append('monorepo-pr-close.yml')
        result=subprocess.run(['actionlint','-shellcheck=',*[str(ROOT/'.github/workflows'/name) for name in names]],cwd=ROOT,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
