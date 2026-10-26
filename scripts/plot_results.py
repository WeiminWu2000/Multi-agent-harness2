"""Render measured performance and revision retention from the public result rows."""
import argparse,json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',type=Path,default=ROOT/'results/study.json');p.add_argument('--output',type=Path,default=ROOT/'results/figures');a=p.parse_args()
 d=json.loads(a.input.read_text());a.output.mkdir(parents=True,exist_ok=True)
 methods=['plain_ds_star','mass_rhi','glm_coordination'];labels=['Base GLM team','MASS-RHI','GLM Harness²'];colors=['#8795a5','#d88c42','#26867b']
 plt.rcParams.update({'font.size':9,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42})
 fig,ax=plt.subplots(1,2,figsize=(8,3.2))
 for i,m in enumerate(methods):
  rr=[r for r in d['rows'] if r['method']==m and r['completed']];n=len(rr);s=sum(r['success'] for r in rr)
  ax[0].bar(i,100*s/n,color=colors[i]);ax[0].text(i,100*s/n+1,f'{s}/{n}',ha='center')
 ax[0].set_xticks(range(3),labels,rotation=12);ax[0].set_ylim(0,45);ax[0].set_ylabel('Official success (%)');ax[0].set_title('Same 38 machine-graded tasks')
 fields=['coord_proposed','coord_composed','coord_retained']
 for j,m in enumerate(['glm_coordination','codex_coordination_harness2']):
  r=d['retention'][m];vs=[100*r[k]/r['entered'] for k in fields];xs=[i+(j-.5)*.35 for i in range(3)]
  ax[1].bar(xs,vs,.35,label=f'{"GLM" if j==0 else "Codex"} editor ({r["entered"]} rounds)',color=['#26867b','#5e67a4'][j])
 ax[1].set_xticks(range(3),['Changed proposal','Composition','Retention'],rotation=12);ax[1].set_ylabel('% of entered rounds');ax[1].set_ylim(0,120);ax[1].legend(frameon=False,fontsize=7);ax[1].set_title('Coordination edits on different task sets')
 fig.tight_layout();fig.savefig(a.output/'study.pdf');fig.savefig(a.output/'study.png',dpi=180);plt.close(fig)
 print('Wrote',a.output/'study.pdf','and study.png')
if __name__=='__main__':main()
