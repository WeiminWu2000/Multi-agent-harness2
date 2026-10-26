"""Actual-USD transport adapter for the recovered DS-STAR controller."""
from dataclasses import dataclass
from mah2.gateway import BudgetExceeded

class ProviderError(RuntimeError):
    pass

@dataclass
class Budget:
    cap: float
    input_rate: float = .37
    output_rate: float = 1.25
    charged: float = 0.0

ACTIVE_GATEWAY = None

class Client:
    def __init__(self,config,budget,ledger,stage='plain'):
        self.c,self.budget,self.g=config,budget,ACTIVE_GATEWAY
        if self.g is None:raise RuntimeError('No bound budget gateway')
        self.g.set_stage(ledger.parent.name+'/'+stage,budget.cap)
        self.start=self.g.charged
    def complete(self,prompt,role=None):
        # Preserve the recovered controller's 15% finalization reservation.
        self.g.stage_cap=self.budget.cap*(.85 if role in ('analyzer','planner','coder','verifier','router','debugger') else 1.)
        payload={'messages':[{'role':'user','content':prompt}],'max_tokens':8192}
        if role in ('proposal_a','proposal_b','composer','selector','reflector'):
            payload['response_format']={'type':'json_object'}
        try:
            result=self.g.request(payload)
            answer=result['choices'][0]['message'].get('content')
            if not isinstance(answer,str) or not answer.strip():raise ProviderError('Empty answer')
            return answer
        except BudgetExceeded:raise
        except Exception as exc:raise ProviderError(type(exc).__name__) from exc
        finally:self.budget.charged=self.g.charged-self.start


class CoordinationClient(Client):
    """GLM transport with the hybrid coordination editor's prefix and call cap."""
    def __init__(self,config,budget,ledger,stage='proposal_b'):
        if stage!='proposal_b':raise ValueError('Coordination client requires proposal_b')
        super().__init__(config,budget,ledger,stage)
        self.calls=0
    def complete(self,prompt,role=None):
        if role!='proposal_b':raise ProviderError('Unexpected coordination role')
        if self.calls>=4:raise BudgetExceeded('GLM coordination call limit reached')
        self.calls+=1
        prefix=('You are the coordination editor in a scientific-agent experiment. All permitted evidence is in this prompt. '
                'Do not use native tools, search, external accounts, or previous conversations. '
                'Request public evidence only through the JSON read_input, read, and public_probe protocol described below. '
                'Do not solve the scientific task or write a submission. Return one JSON object only.\n')
        return super().complete(prefix+prompt,role)
