"""Recompute strict pass counts and paired exact tests from the published task rows."""
import argparse,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=ROOT/'results/study.json');a=p.parse_args()
 d=json.loads(a.input.read_text()); rows=d['rows']; methods=list(d['summary'])
 for m in methods:
  rr=[r for r in rows if r['method']==m and r['completed']]
  count=sum(r['success'] for r in rr)
  assert count==d['summary'][m]['passed'] and len(rr)==d['summary'][m]['completed']
  print(f'{m}: {count}/{len(rr)}; provider USD {sum(r.get("cost") or 0 for r in rr):.2f}')
 for a,b in [('glm_coordination','mass_rhi'),('codex_coordination_harness2','mass_rhi')]:
  x={r['task']:r['success'] for r in rows if r['method']==a and r['completed']};y={r['task']:r['success'] for r in rows if r['method']==b and r['completed']};ids=x.keys()&y.keys();w=sum(x[t]>y[t] for t in ids);l=sum(x[t]<y[t] for t in ids);n=w+l
  p=min(1,2*sum(math.comb(n,k) for k in range(min(w,l)+1))/2**n) if n else 1
  print(f'{a} vs {b}: matched={len(ids)}, wins={w}, losses={l}, exact_p={p:.6f}')
if __name__=='__main__':main()
