"""Shared benchmark sandbox for DS-STAR; no gold targets or credentials mounted."""
from pathlib import Path
from mah2.runtime import ROOT,base_command,run_process,hashes as manifest

class Sandbox:
    def __init__(self,root,data,config):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.data,self.config,self.sequence=data,config,0
    def run(self,code,name='program.py',timeout=None):
        if Path(name).name!=name or not name.endswith('.py'):raise ValueError('Invalid script filename')
        (self.root/name).write_text(code);self.sequence+=1
        science=ROOT/self.config['science_environment']
        seconds=max(1,int(min(timeout or self.config['execution_seconds'],self.config['execution_seconds'])))
        result=run_process(base_command(self.root,self.data,science=science)+[str(science/'bin/python'),name],self.root/f'.execution_{self.sequence}',seconds)
        result['artifacts']=manifest(self.root/'pred_results')
        return result
