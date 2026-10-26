"""Host-only API gateway: all solver/editor/judge calls share a dollar ledger."""
import http.server
import os
import json
import secrets
import socketserver
import threading
import time
import tempfile
from pathlib import Path
import requests


def load_api_key():
    """Read host-only credentials without copying them into experiment artifacts."""
    key = os.environ.get('OPENROUTER_API_KEY', '').strip()
    if not key and os.environ.get('OPENROUTER_API_KEY_FILE'):
        key = Path(os.environ['OPENROUTER_API_KEY_FILE']).expanduser().read_text().strip()
    if not key:
        raise RuntimeError('Set OPENROUTER_API_KEY or OPENROUTER_API_KEY_FILE before executing paid calls')
    return key


class BudgetExceeded(RuntimeError):
    pass


class Gateway:
    def __init__(self, directory, config, cap=1.0, session=None):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.config=config;self.cap=cap;self.charged=0.0;self.calls=[]
        self.stage='setup';self.stage_cap=cap;self.stage_start=0.0
        self.lock=threading.Lock();self.session=session or requests.Session()
        self.key=load_api_key() if session is None else 'fixture'
        self.token=secrets.token_hex(24)
        self.socket_path=Path(tempfile.gettempdir())/('mah2-'+secrets.token_hex(10)+'.sock')

    def set_stage(self,name,cap):
        # Finish any in-flight call before changing its accounting stage.
        with self.lock:
            self.stage=name;self.stage_cap=min(cap,self.cap-self.charged);self.stage_start=self.charged

    @property
    def remaining(self):
        return max(0.,self.cap-self.charged)

    def request(self,payload):
        # Serial reservation also covers parallel subagents; no double-spend race.
        with self.lock:
            p=dict(payload);p['model']=self.config['model'];p['stream']=False
            p.pop('stream_options',None)
            p.pop('chat_template_kwargs',None)
            p.pop('repetition_penalty',None)
            p['provider']={'only':[self.config.get('provider_slug','chutes')],'allow_fallbacks':False}
            if not self.config.get('supports_response_format',False):p.pop('response_format',None)
            p['reasoning']=self.config.get('reasoning',{'enabled':False})
            p['usage']={'include':True}
            p['temperature']=0.6
            p['top_p']=0.95
            if self.config.get('supports_seed',True):p['seed']=20261023
            else:p.pop('seed',None)
            # UTF-8 bytes, plus envelope/tool framing, conservatively bound input tokens.
            input_bound=len(json.dumps(p,ensure_ascii=False).encode())+4096
            rates=self.config['budget'];ir=rates['input_per_million']/1e6;orr=rates['output_per_million']/1e6
            left=min(self.remaining,self.stage_cap-(self.charged-self.stage_start))
            output_cap=min(int(p.get('max_tokens',8192)),8192,int((left-input_bound*ir)/orr))
            if output_cap<128:raise BudgetExceeded('stage or task dollar allowance exhausted')
            p['max_tokens']=output_cap
            reserved=input_bound*ir+output_cap*orr
            self.charged+=reserved
            index=len(self.calls);start=time.monotonic()
            rec={'index':index,'stage':self.stage,'reserved_usd':reserved,'input_bound':input_bound,'max_output_tokens':output_cap}
            (self.directory/f'call_{index:04d}_request.json').write_text(json.dumps(p))
            pending=self.directory/f'call_{index:04d}_pending.json'
            pending.write_text(json.dumps(rec))
            try:
                response=self.session.post('https://openrouter.ai/api/v1/chat/completions',json=p,
                    headers={'Authorization':'Bearer '+self.key},timeout=(15,150))
                if getattr(response,'status_code',200)>=400:
                    # Preserve provider diagnostics without authorization headers.
                    detail={'status_code':response.status_code,
                            'headers':{k:v for k,v in response.headers.items() if k.lower() in
                                ('retry-after','x-request-id','x-ratelimit-limit','x-ratelimit-remaining','x-ratelimit-reset')},
                            'body':response.text[:16000].replace(self.key,'<redacted>')}
                    (self.directory/f'call_{index:04d}_error.json').write_text(json.dumps(detail,indent=2))
                    rec.update(http_status=response.status_code,retry_after=response.headers.get('Retry-After'))
                response.raise_for_status();data=response.json()
                if 'error' in data:raise RuntimeError(str(data['error']))
                if not data.get('choices'):raise RuntimeError('Missing choices')
                usage=data.get('usage') or {}
                # No usage -> retain full reservation. Cached-input savings settle normally.
                actual=usage.get('cost')
                if actual is None and 'prompt_tokens' in usage and 'completion_tokens' in usage:
                    actual=usage['prompt_tokens']*ir+usage['completion_tokens']*orr
                if actual is not None:
                    actual=float(actual)
                    if actual<0:raise RuntimeError('Negative usage cost')
                    self.charged+=actual-reserved
                rec.update(usage=usage,charged_usd=actual if actual is not None else reserved,status='returned')
                (self.directory/f'call_{index:04d}_response.json').write_text(json.dumps(data))
                return data
            except Exception as exc:
                # An uncertain failed request remains fully charged; no invisible retries.
                rec.update(status='failed',error=type(exc).__name__,charged_usd=reserved)
                raise
            finally:
                rec.update(seconds=time.monotonic()-start,total_charged_usd=self.charged)
                self.calls.append(rec)
                with (self.directory/'ledger.jsonl').open('a') as f:f.write(json.dumps(rec)+'\n')
                (self.directory/'cost.json').write_text(json.dumps({'cap_usd':self.cap,'charged_usd':self.charged,'calls':len(self.calls)}))
                pending.unlink(missing_ok=True)

    def chat(self,system,user):
        d=self.request({'messages':[{'role':'system','content':system},{'role':'user','content':user}],
                        'max_tokens':4096,'response_format':{'type':'json_object'}})
        raw=d['choices'][0]['message'].get('content') or ''
        value=json.loads(raw)
        if not isinstance(value,dict):raise ValueError('Expected JSON object')
        return value

    def start(self):
        gateway=self
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def send(self,status,data,kind='application/json'):
                body=data if isinstance(data,bytes) else json.dumps(data).encode()
                self.send_response(status);self.send_header('Content-Type',kind)
                self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
            def do_GET(self):
                self.send(200,{'data':[{'id':gateway.config['model'],'object':'model'}]})
            def do_POST(self):
                if self.headers.get('Authorization')!='Bearer '+gateway.token:
                    return self.send(401,{'error':{'message':'invalid gateway token','type':'auth_error'}})
                try:
                    if self.path!='/v1/chat/completions':raise ValueError('unsupported endpoint')
                    n=int(self.headers.get('Content-Length','0'))
                    if n>3_000_000:raise ValueError('request exceeds gateway bound')
                    p=json.loads(self.rfile.read(n));stream=p.get('stream',False)
                    d=gateway.request(p)
                    if not stream:return self.send(200,d)
                    # Buffer upstream completion, then encode OpenAI SSE for qwen-code.
                    choice=d['choices'][0];msg=dict(choice['message'])
                    for i,tc in enumerate(msg.get('tool_calls') or []):tc['index']=i
                    base={k:d[k] for k in ['id','created','model'] if k in d};base['object']='chat.completion.chunk'
                    chunks=[{**base,'choices':[{'index':0,'delta':msg,'finish_reason':None}]},
                            {**base,'choices':[{'index':0,'delta':{},'finish_reason':choice.get('finish_reason','stop')}],'usage':d.get('usage',{})}]
                    body=(''.join('data: '+json.dumps(x)+'\n\n' for x in chunks)+'data: [DONE]\n\n').encode()
                    self.send(200,body,'text/event-stream')
                except BudgetExceeded as exc:self.send(402,{'error':{'message':str(exc),'type':'budget_exhausted'}})
                except Exception as exc:self.send(502,{'error':{'message':type(exc).__name__,'type':'gateway_error'}})
        class Server(socketserver.ThreadingMixIn,socketserver.UnixStreamServer):
            daemon_threads=True
        self.server=Server(str(self.socket_path),Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        return self

    def close(self):
        if hasattr(self,'server'):self.server.shutdown();self.server.server_close()
        self.socket_path.unlink(missing_ok=True)
