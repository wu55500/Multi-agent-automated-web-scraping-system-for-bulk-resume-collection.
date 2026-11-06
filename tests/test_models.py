import json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from dz.platform.models import Models,analyze_models,generate_project
from dz.platform.store import Store
from dz.platform.benchmark import evaluate_sample


class ModelTests(unittest.TestCase):
    def model(self,outputs):
        outputs=iter(outputs)
        def transport(url,**kw):
            self.assertEqual(kw['headers']['Authorization'],'Bearer test')
            return 200,{},json.dumps({'choices':[{'message':{'content':json.dumps(next(outputs))}}]}).encode()
        config={r:{'base':'https://example.com/v1','key_env':'TEST_MODEL_KEY','model':'fixture-model'} for r in ['analyst','reviewer','builder']}
        return Models(config,transport)
    def test_missing_key_fails(self):
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError):self.model([]).call('analyst','x',{})
    @patch.dict(os.environ,{'TEST_MODEL_KEY':'test'})
    def test_actual_transport_called(self):
        result,trace=self.model([{'answer':42}]).call('analyst','x',{})
        self.assertEqual(result['answer'],42);self.assertEqual(trace['model'],'fixture-model')
    @patch.dict(os.environ,{'TEST_MODEL_KEY':'test'})
    def test_evidence_rejects_hallucination(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root);s.register('a','json',consent='test',compliance='approved');s.ingest('a',[{'id':'1','title':'Python','raw':'Python required'}])
            with self.assertRaises(ValueError):analyze_models(s,s.jobs()[0]['id'],self.model([{'skills':[{'name':'Java','evidence':'Java required'}]}]))
            s.close()
    @patch.dict(os.environ,{'TEST_MODEL_KEY':'test'})
    def test_two_model_disagreement(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root);s.register('a','json',consent='test',compliance='approved');s.ingest('a',[{'id':'1','title':'Python','raw':'Python and SQL required'}])
            result=analyze_models(s,s.jobs()[0]['id'],self.model([{'skills':[{'name':'Python','evidence':'Python'},{'name':'SQL','evidence':'SQL'}]},{'skills':[{'name':'Python','evidence':'Python'}]}]))
            self.assertEqual(len(result['agreed']),1);self.assertEqual(len(result['needs_review']),1);s.close()
    @patch.dict(os.environ,{'TEST_MODEL_KEY':'test'})
    def test_generated_project_not_executed(self):
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/'project'
            result=generate_project(self.model([{'files':[{'path':'main.py','content':'raise RuntimeError("must not execute")'}]},{'approved':True,'issues':[]}]),'test',out)
            self.assertFalse(result['executed']);self.assertTrue((out/'main.py').is_file())
    @patch.dict(os.environ,{'TEST_MODEL_KEY':'test'})
    def test_path_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):generate_project(self.model([{'files':[{'path':'../escape.py','content':'x=1'}]}]),'test',Path(root)/'out')
    @patch.dict(os.environ,{'TEST_MODEL_KEY':'test'})
    def test_model_review_blocks_project(self):
        with tempfile.TemporaryDirectory() as root:
            out=Path(root)/'out'
            with self.assertRaises(ValueError):generate_project(self.model([{'files':[{'path':'main.py','content':'x=1'}]},{'approved':False,'issues':['bad']}]),'test',out)
            self.assertFalse(out.exists())
    def test_small_sample_not_90_proof(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root);s.register('a','json',consent='test',compliance='approved');s.ingest('a',[{'id':'1','title':'Python','raw':'Python required'}])
            r=evaluate_sample(s,{'canonical_ids':[s.jobs()[0]['canonical_id']],'provenance':'independent fixture'})
            self.assertEqual(r['sample_coverage'],1);self.assertFalse(r['sample_lower_bound_at_least_90_percent']);s.close()
    def test_duplicate_sample_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            s=Store(root)
            with self.assertRaises(ValueError):evaluate_sample(s,{'canonical_ids':['x','x'],'provenance':'test'})
            s.close()

if __name__=='__main__':unittest.main()
