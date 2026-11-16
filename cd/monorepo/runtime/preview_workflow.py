"""Protected preview orchestration, after admission to the fixed writer group.

The central entry owns caller/code/environment verification and private credential
setup. Runtime callbacks below are fixed trusted Python, not bundle fields or
operator YAML. A replaced pending close event is not a lossless queue: every
admitted route converges the CURRENT PR before opening any source artifacts.
"""
from preview import IaCPreview, cleanup, reconcile_preview, verify_pr
from contracts import fail


def dispatch_admitted(github, repository, pr, target, *, admit, close_runtime, preview_runtime):
    """Converge current state before stale-head/artifact/scanner preview gates.

    `admit` independently verifies the exact current host/caller and common
    repository/PR/target concurrency group. It MUST NOT download source artifacts
    or require scans. `close_runtime` independently authorizes standing closure
    policy using historical native handles, never manual confirmation authority.
    `preview_runtime` performs source/stage/current-head/scan checks for rollout.
    No callback is selected or deserialized from user-controlled data.
    """
    admit(repository,pr,target)
    current=github.repo('GET','/pulls/'+str(pr))
    closed=current and current.get('state')=='closed'
    verify_pr(current,repository,closed=closed)
    if closed:
        context=close_runtime(repository,pr,target,current)
        controller=IaCPreview(github,repository,pr,target,current['head']['sha'],context)
        controller.close()
        return {'phase':'closed','pr':pr,'target':target}
    # Includes reopened PRs: standing closure performs NO deletion. The normal
    # preview factory still must deny a stale triggering head before rollout.
    return preview_runtime(repository,pr,target,current)


def run_preview(github, repository, pr, run, trusted_plan, plan, results, target,
                publisher, root, store, *, context):
    """Execute a fully prepared and bound preview with private runtime context."""
    controller=IaCPreview(github,repository,pr,target,plan['headSha'],context)
    local=dict(context,controller=controller)
    return reconcile_preview(context['cloud'],github,repository,pr,run,trusted_plan,
        plan,results,target,publisher,root,store,context=local)


def main():
    # Workflow-owned flags/artifact JSON can never supply the trusted process
    # callbacks. Central fixed entry constructs them after protected admission.
    fail('preview-entrypoint','use the protected central preview entry')


if __name__=='__main__':
    main()
