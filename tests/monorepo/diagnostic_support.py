"""Keep structured evidence from unit tests outside every product worktree."""
import atexit
import os
import tempfile

if 'CLOUDOPSWORKS_DIAGNOSTICS' not in os.environ:
    _directory=tempfile.TemporaryDirectory(prefix='cloudopsworks-test-diagnostics-')
    os.environ['CLOUDOPSWORKS_DIAGNOSTICS']=_directory.name
    atexit.register(_directory.cleanup)
