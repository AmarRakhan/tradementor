import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent

class WorkflowContractTest(unittest.TestCase):
    def test_workflow_manual_only(self):
        txt = (ROOT/'short-recovery-601-readonly.yml').read_text()
        self.assertIn('workflow_dispatch:', txt)
        for forbidden in ('  push:', '  create:', '  pull_request:', '  workflow_run:', '  schedule:'):
            self.assertNotIn(forbidden, txt)
    def test_no_deploy_or_order_commands(self):
        txt = (ROOT/'short-recovery-601-readonly.yml').read_text()
        for forbidden in ('update-traffic', 'gcloud run deploy', 'orders create', 'workflow run', 'permissions: write-all'):
            self.assertNotIn(forbidden, txt)
    def test_uses_observer(self):
        txt = (ROOT/'short-recovery-601-readonly.yml').read_text()
        self.assertIn('github-tradementor-observer@tradementor-production.iam.gserviceaccount.com',txt)
    def test_probe_exact_revision_targets(self):
        from rollback_probe import REVISIONS
        self.assertEqual(REVISIONS['web'],'amar-bot-v44-direct-install-v46-89ab74a0-1')
        self.assertEqual(REVISIONS['backend'],'tradementor-api-src-f87d6b20-124369')
