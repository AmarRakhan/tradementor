import unittest
import rollback_probe as m

class ProbeTest(unittest.TestCase):
    def test_pass(self):
        o=m.summarize_revision({'metadata':{'name':'rev'},'status':{'conditions':[{'type':'Ready','status':'True'}]},'spec':{'containers':[{'image':'digest'}]}},'rev')
        self.assertEqual(o['outcome'],'PASS')
    def test_fail_missing_image(self):
        o=m.summarize_revision({'metadata':{'name':'rev'},'status':{'conditions':[{'type':'Ready','status':'True'}]}},'rev')
        self.assertEqual(o['outcome'],'NO_GO')
    def test_fail_wrong_revision(self):
        o=m.summarize_revision({'metadata':{'name':'other'},'status':{'conditions':[{'type':'Ready','status':'True'}]},'spec':{'containers':[{'image':'digest'}]}},'rev')
        self.assertEqual(o['outcome'],'NO_GO')
    def test_failure_no_secret_output(self):
        class P: returncode=1;stdout='';stderr='secret-protected'
        self.assertEqual(m.probe(lambda *a, **kw:P())['web']['reason'],'READ_UNAVAILABLE')
    def test_never_proves_compatibility(self):
        class P: returncode=0;stdout='{}';stderr=''
        self.assertEqual(m.probe(lambda *a, **kw:P())['rollback']['outcome'],'NOT_PROVEN')
if __name__=='__main__':unittest.main()
