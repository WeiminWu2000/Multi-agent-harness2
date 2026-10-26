"""Execute a synthetic join in the real sandbox without model calls or benchmark data."""
import argparse,csv,json,shutil,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from mah2.runtime import base_command,run_process

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--science-env',type=Path,default=ROOT/'.venv-science');a=p.parse_args()
 science=a.science_env.resolve()
 if not (science/'bin/python').is_file():raise SystemExit('Create the science environment first')
 with tempfile.TemporaryDirectory(prefix='mah2-check-') as tmp:
  root=Path(tmp);data=root/'data';shutil.copytree(ROOT/'examples/join/data',data)
  secret=root/'host-only.txt';secret.write_text('synthetic host-only sentinel')
  work=root/'work';work.mkdir()
  code="""import csv, pathlib, socket
assert pathlib.Path.cwd() == pathlib.Path('/work')
assert not pathlib.Path(HOST_SENTINEL).exists(), 'Host files leaked into sandbox'
try:
    pathlib.Path('data/forbidden-write').write_text('should fail')
except OSError:
    pass
else:
    raise AssertionError('Public inputs are writable')
with open('data/labels.csv') as f:
    labels = {r['id']: r['label'] for r in csv.DictReader(f)}
with open('data/values.csv') as f:
    rows = sorted(csv.DictReader(f), key=lambda r:int(r['id']))
with open('pred_results/join.csv','w',newline='') as f:
    w=csv.writer(f);w.writerow(['id','value','label'])
    for r in rows:w.writerow([r['id'],r['value'],labels[r['id']]])
print('sandbox join passed')
""".replace('HOST_SENTINEL',repr(str(secret)))
  (work/'check.py').write_text(code)
  result=run_process(base_command(work,data,science=science)+[str(science/'bin/python'),'check.py'],root/'logs',30)
  if result['returncode']!=0:
   print(json.dumps(result,indent=2));return 1
  with (work/'pred_results/join.csv').open() as f:rows=list(csv.reader(f))
  assert rows==[['id','value','label'],['1','10','A'],['2','20','B']]
  print('PASS: actual sandbox execution, exact join output, read-only public inputs, host-file isolation; zero API calls')
 return 0
if __name__=='__main__':raise SystemExit(main())
