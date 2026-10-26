"""Isolated ChatGPT-authenticated Codex transport for coordination proposals only."""
from __future__ import annotations
import hashlib,json,os,signal,subprocess,time
from pathlib import Path
from .provider import BudgetExceeded,ProviderError

DISABLED=('shell_tool','apps','plugins','remote_plugin','code_mode_host','multi_agent_v2')

def command(work,settings):
    auth=Path(settings['auth_file']).expanduser().resolve()
    binary=Path(settings['binary']).expanduser().resolve()
    if not auth.is_file() or not binary.is_file():raise ProviderError('Codex authentication or executable unavailable')
    args=['bwrap','--unshare-all','--share-net','--die-with-parent','--new-session','--clearenv',
          '--proc','/proc','--dev','/dev','--tmpfs','/tmp','--tmpfs','/codex-home']
    for name in ('/usr','/bin','/lib','/lib64','/etc/ssl','/etc/pki','/etc/resolv.conf','/etc/hosts','/etc/nsswitch.conf'):
        if Path(name).exists():args+=['--ro-bind',name,name]
    args+=['--ro-bind',str(binary),'/codex','--ro-bind',str(auth),'/codex-home/auth.json',
           '--bind',str(work.resolve()),'/work','--chdir','/work',
           '--setenv','HOME','/tmp','--setenv','CODEX_HOME','/codex-home','--setenv','PATH','/usr/bin:/bin']
    for name in ('SSL_CERT_FILE','SSL_CERT_DIR'):
        if os.environ.get(name):args+=['--setenv',name,os.environ[name]]
    args+=['/codex','exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check',
           '-s','read-only','-m',settings['model'],'-c','model_reasoning_effort='+json.dumps(settings['reasoning_effort']),
           '-c','web_search="disabled"','--json','-o','/work/answer.txt']
    for feature in DISABLED:args+=['--disable',feature]
    return args+['-']

class Client:
    def __init__(self,config,budget,ledger,stage='proposal_b'):
        if stage!='proposal_b':raise ValueError('Codex may only serve the coordination proposal')
        self.c=config['codex_coordination'];self.budget=budget
        self.root=Path(ledger).parent/'codex_proposal_b';self.root.mkdir(exist_ok=True)
        self.calls=0
    def complete(self,prompt,role=None):
        if role!='proposal_b':raise ProviderError('Unexpected Codex role')
        if self.calls>=self.c['max_calls_per_round']:raise BudgetExceeded('Codex coordination call limit reached')
        work=self.root/f'call_{self.calls:02d}';work.mkdir();self.calls+=1
        prefix=('You are the coordination editor in a scientific-agent experiment. All permitted evidence is in this prompt. '
                'Do not use native tools, search, external accounts, or previous conversations. '
                'Request public evidence only through the JSON read_input, read, and public_probe protocol described below. '
                'Do not solve the scientific task or write a submission. Return one JSON object only.\n')
        request=prefix+prompt;(work/'prompt.txt').write_text(request)
        record=dict(model=self.c['model'],reasoning_effort=self.c['reasoning_effort'],stage=role,
                    prompt_sha256=hashlib.sha256(request.encode()).hexdigest(),billing='ChatGPT Codex usage; USD unavailable',
                    cost_usd=None,status='started',usage=None)
        (work/'request.json').write_text(json.dumps(record,indent=2))
        start=time.monotonic()
        try:
            with (work/'events.jsonl').open('w') as out,(work/'stderr.txt').open('w') as err:
                p=subprocess.Popen(command(work,self.c),stdin=subprocess.PIPE,stdout=out,stderr=err,text=True,start_new_session=True)
                try:p.communicate(request,timeout=self.c['timeout_seconds'])
                except subprocess.TimeoutExpired:
                    os.killpg(p.pid,signal.SIGKILL);p.wait();raise ProviderError('Codex coordination timed out')
            events=[]
            for line in (work/'events.jsonl').read_text().splitlines():
                try:events.append(json.loads(line))
                except json.JSONDecodeError:pass
            turns=[e for e in events if e.get('type')=='turn.completed']
            if turns:record['usage']=turns[-1].get('usage')
            if p.returncode or not turns or not (work/'answer.txt').is_file():raise ProviderError('Codex invocation failed; see isolated event log')
            answer=(work/'answer.txt').read_text()
            if not answer.strip():raise ProviderError('Empty Codex response')
            record['status']='completed';return answer
        except (OSError,RuntimeError) as exc:
            record.update(status='failed',error=str(exc));raise ProviderError(str(exc)) from exc
        finally:
            record['seconds']=time.monotonic()-start
            (work/'result.json').write_text(json.dumps(record,indent=2))
            with (self.root/'usage.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
            # This is GLM dollar accounting only. Codex usage is never labelled free.
            self.budget.charged=0.

def usage(root):
    rows=[]
    for p in Path(root).glob('optimization/round_*/codex_proposal_b/usage.jsonl'):
        rows.extend(json.loads(line) for line in p.read_text().splitlines() if line)
    fields=('input_tokens','cached_input_tokens','output_tokens','reasoning_output_tokens')
    return dict(calls=len(rows),failed_calls=sum(r['status']!='completed' for r in rows),
                usage_missing_calls=sum(r['usage'] is None for r in rows),
                **{k:sum((r['usage'] or {}).get(k,0) for r in rows) for k in fields},
                cost_usd=None,billing='ChatGPT Codex usage; separate from GLM API dollars')
