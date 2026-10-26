import contextlib,io,json,os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mah2.cli import main
from mah2.gateway import load_api_key
ROOT=Path(__file__).resolve().parents[1]
class ReleaseTests(unittest.TestCase):
 def args(self,output):return ['--task',str(ROOT/'examples/join/task.json'),'--data',str(ROOT/'examples/join/data'),'--output',str(output)]
 def test_default_check_makes_no_calls_or_files(self):
  with tempfile.TemporaryDirectory() as tmp,patch('mah2.gateway.Gateway',side_effect=AssertionError('No API calls')):
   output=Path(tmp)/'new';stream=io.StringIO()
   with contextlib.redirect_stdout(stream):self.assertEqual(main(self.args(output)),0)
   self.assertFalse(output.exists());self.assertFalse(json.loads(stream.getvalue())['paid_calls'])
 def test_rejects_existing_output_and_over_budget(self):
  with tempfile.TemporaryDirectory() as tmp,contextlib.redirect_stderr(io.StringIO()):
   for args in [self.args(tmp),self.args(Path(tmp)/'new')+['--budget','2']]:
    with self.assertRaises(SystemExit):main(args)
 def test_credentials_from_environment_and_file(self):
  with patch.dict(os.environ,{'OPENROUTER_API_KEY':'fixture-value'},clear=True):self.assertEqual(load_api_key(),'fixture-value')
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'key';p.write_text('fixture-file\n')
   with patch.dict(os.environ,{'OPENROUTER_API_KEY_FILE':str(p)},clear=True):self.assertEqual(load_api_key(),'fixture-file')
  with patch.dict(os.environ,{},clear=True):
   with self.assertRaises(RuntimeError):load_api_key()
 def test_rejects_output_inside_public_data(self):
  with contextlib.redirect_stderr(io.StringIO()),self.assertRaises(SystemExit):main(self.args(ROOT/'examples/join/data/output'))
 def test_release_scanner_rejects_tokens_and_private_artifacts(self):
  from scripts.check_release import check_content
  token=('sk-or-'+'v1-'+'a'*64).encode()
  self.assertTrue(check_content('innocent.txt',token))
  self.assertTrue(check_content('private/task.json',b'{}'))
  self.assertFalse(check_content('README.md',b'export OPENROUTER_API_KEY_FILE=/path/to/key'))
