"""Audit tracked files and reachable Git history without displaying secret values."""
import re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BLOCKED={'private','runs','vendor','.runtime','overleaf'}
PATTERNS=[
 re.compile(rb'sk-or-v1-[a-fA-F0-9]{32,}'),
 re.compile(rb'\bolp_[A-Za-z0-9]{20,}'),
 re.compile(rb'\bgh[pousr]_[A-Za-z0-9]{30,}'),
 re.compile(rb'github_pat_[A-Za-z0-9_]{30,}'),
 re.compile(rb'sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{40,}'),
 re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----'),
 re.compile(rb'/(?:gpfs)/(?:home|projects)/'),
 re.compile(rb'/home/[A-Za-z][A-Za-z0-9_-]*/'),
]
def check_content(name,raw):
 errors=[];parts=Path(name).parts
 if set(parts)&BLOCKED or any(p.startswith('.venv') for p in parts):errors.append('private/runtime directory')
 if Path(name).name in {'auth.json','.env'} or name.endswith('.key'):errors.append('credential filename')
 if any(pattern.search(raw) for pattern in PATTERNS):errors.append('credential or private-path pattern')
 return errors

def main():
 tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).decode().split('\0');failures=[];count=0
 for name in filter(None,tracked):
  p=ROOT/name;count+=1
  if p.is_symlink():failures.append((name,'tracked symlink'));continue
  if not p.is_file():failures.append((name,'missing tracked file'));continue
  failures.extend((name,e) for e in check_content(name,p.read_bytes()))
 # Scan historical file versions too; deleting a current file cannot clean Git history.
 head=subprocess.run(['git','rev-parse','--verify','HEAD'],cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 blobs=0
 if head.returncode==0:
  objects=subprocess.check_output(['git','rev-list','--objects','--all'],cwd=ROOT,text=True)
  for entry in objects.splitlines():
   bits=entry.split(' ',1)
   if len(bits)!=2:continue
   oid,name=bits
   if subprocess.check_output(['git','cat-file','-t',oid],cwd=ROOT,text=True).strip()!='blob':continue
   blobs+=1;raw=subprocess.check_output(['git','cat-file','blob',oid],cwd=ROOT)
   failures.extend((name+' [history]',e) for e in check_content(name,raw))
 if failures:
  for name,reason in failures:print(f'FAIL {name}: {reason}')
  return 1
 print(f'PASS: {count} tracked files, {blobs} historical blobs; no blocked paths, tracked symlinks, or recognized secret patterns')
 print('Pattern audit is not a guarantee that all sensitive content has been detected.')
 return 0
if __name__=='__main__':raise SystemExit(main())
