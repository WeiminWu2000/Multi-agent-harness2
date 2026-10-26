"""Fetch exact upstream revisions into an ignored directory; never overwrite a checkout."""
import argparse,json,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEPENDENCIES={
 'ds-star':('https://github.com/google-research/ds-star.git','6c05b01e30f01489af12708e99eda932e44d10ba'),
 'harness2':('https://github.com/google-research/harness2.git','1cfe254e8d25b15f37048c3730134686abe60335'),
 'mass':('https://github.com/SakanaAI/mass.git','fb403581bed2c974b3f99e7236224169da643079')}
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--include-mass',action='store_true',help='Obtain MASS separately; its upstream NOTICE does not assign an open-source license');a=p.parse_args()
 for name,(url,rev) in DEPENDENCIES.items():
  if name=='mass' and not a.include_mass:continue
  dest=ROOT/'vendor'/name
  if dest.exists():
   actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip()
   dirty=subprocess.check_output(['git','status','--porcelain'],cwd=dest,text=True).strip()
   if actual!=rev or dirty:raise SystemExit(f'{name}: existing checkout differs; inspect it manually')
   print(name,'already pinned');continue
  dest.mkdir(parents=True)
  for cmd in [['git','init','-q'],['git','remote','add','origin',url],['git','fetch','--depth','1','origin',rev],['git','checkout','--detach','FETCH_HEAD']]:subprocess.run(cmd,cwd=dest,check=True)
  assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip()==rev
  print(name,rev)
if __name__=='__main__':main()
