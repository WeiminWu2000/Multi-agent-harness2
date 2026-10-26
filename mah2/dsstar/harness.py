"""Shared bounded edit surface; the baseline can edit every treatment field."""
from __future__ import annotations
import copy

ROLES = ('analyzer','planner','coder','verifier','router','debugger','finalizer')
INTERFACES = {'analyzer.planner','planner.coder','coder.verifier','verifier.router',
              'router.planner','verifier.planner','verifier.finalizer','coder.finalizer'}
STATE_FIELDS = {'question','filenames','file_descriptions','plans','code','execution','verification','routing'}
FUNCTION_ROLE = dict(code_for_analyze='analyzer',debug_for_analyze='debugger',
    bug_summarization='debugger',debug_with_context='debugger',initial_plan='planner',
    next_plan='planner',initial_implementation='coder',implement='coder',verify='verifier',
    router='router',match_guideline='finalizer')

def initial():
    return dict(roles={r:'' for r in ROLES},coordination=dict(version=1,
        verifier_diagnosis=False,router_receives_diagnosis=False,
        planner_receives_diagnosis=False,coder_receives_question=False,contracts={}))

def validate(candidate, base, scope):
    if set(candidate) != {'roles','coordination'} or set(candidate['roles']) != set(ROLES):
        raise ValueError('invalid edit surface')
    if any(not isinstance(v,str) or len(v)>12000 for v in candidate['roles'].values()):
        raise ValueError('invalid role instruction')
    c = candidate['coordination']
    if set(c) != set(initial()['coordination']): raise ValueError('invalid coordination schema')
    if type(c['version']) is not int or c['version'] < 1: raise ValueError('invalid version')
    if any(type(v) is not bool for k,v in c.items() if k not in ('version','contracts')): raise ValueError('invalid routing option')
    if (c['router_receives_diagnosis'] or c['planner_receives_diagnosis']) and not c['verifier_diagnosis']:
        raise ValueError('consumer requires producer diagnosis')
    contracts=c['contracts']
    if not isinstance(contracts,dict) or not set(contracts)<=INTERFACES:
        raise ValueError('unknown interface')
    for edge,contract in contracts.items():
        if set(contract)!={'version','fields','sender_instruction','receiver_instruction'}:
            raise ValueError('contract schema invalid')
        if contract['version']!=c['version']:raise ValueError('inconsistent contract version')
        if not isinstance(contract['fields'],list) or not set(contract['fields'])<=STATE_FIELDS:
            raise ValueError('unavailable state field')
        if any(not isinstance(contract[k],str) or len(contract[k])>6000 for k in ('sender_instruction','receiver_instruction')):
            raise ValueError('invalid interface instruction')
    changed = [r for r in ROLES if candidate['roles'][r]!=base['roles'][r]]
    coord_changed = c != base['coordination']
    if coord_changed and c['version']<=base['coordination']['version']: raise ValueError('contract version must increase')
    if scope=='local' and (len(changed)>1 or coord_changed): raise ValueError('local edit crosses interface')
    if scope=='coordination' and changed and not coord_changed: raise ValueError('coordination edit requires declared contract')
    if scope=='coordination' and coord_changed:
        # A shared-version bump must refresh untouched contracts too. Count
        # semantic route changes, not their mandatory version synchronization.
        def semantic(contract):
            return {k:v for k,v in contract.items() if k!='version'} if contract is not None else None
        changed_edges={edge for edge in set(contracts)|set(base['coordination']['contracts'])
                       if semantic(contracts.get(edge))!=semantic(base['coordination']['contracts'].get(edge))}
        coder_route=c['coder_receives_question']!=base['coordination']['coder_receives_question']
        feedback_route=any(c[k]!=base['coordination'][k] for k in ('verifier_diagnosis','router_receives_diagnosis','planner_receives_diagnosis'))
        routes=len(changed_edges)+int(coder_route)+int(feedback_route)
        if routes>1:raise ValueError('coordination proposal must target one route: choose one contract OR coder-question boolean OR diagnosis booleans; do not combine mechanisms')
        permitted=set()
        for edge in changed_edges:permitted.update(edge.split('.'))
        if coder_route:permitted.update(('coder','planner'))
        if feedback_route:permitted.update(('verifier','router','planner'))
        if not set(changed)<=permitted:raise ValueError('role edit outside targeted route')
    return copy.deepcopy(candidate)
