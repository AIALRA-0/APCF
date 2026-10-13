# APCF-META {"schema":1,"visibility":"public"}
"""Cooperative per-request witness and guarded file writes.

This program controls only calls routed through it. An ordinary same-user shell can
bypass it. Bind request/resume/write/output events in the actual host before claiming
automatic multi-turn enforcement. No Dify/LangGraph runtime is a dependency.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import uuid
from repair_io import canonical, digest, inside, lock, normalized, private_json, text_digest, atomic

ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT/'.agent-project-control'


def now(): return datetime.now(timezone.utc).isoformat()


def authority(root=None):
    root=Path(ROOT if root is None else root)
    paths=[root/'AGENTS.md',root/'.agent-project-control/routing.toml',root/'.agent-project-control/gate.toml']
    for sub in ('rules','standards','interfaces','design'):
        directory=root/'.agent-project-control'/sub
        paths += [p for p in directory.rglob('*') if p.is_file() and p.suffix in {'.md','.toml','.yaml'} and 'components' not in p.parts]
    return {p.relative_to(root).as_posix():digest(p.read_bytes()) for p in sorted(set(paths)) if p.is_file()}


def _safe_turn(turn):
    turn=Path(turn).resolve()
    if not turn.is_relative_to((CONTROL/'iterations').resolve()) or not (turn/'REQUEST.md').is_file():
        raise ValueError('use an actual current project TR; do not reuse a VPS/source template TR')
    return turn


def begin(turn, request_id=None, *, rollback_state=None):
    turn=_safe_turn(turn)
    p=turn/'evidence/execution-session.json'
    with lock(CONTROL/'runtime/tmp/.session.lock'):
        if p.exists(): raise ValueError('session already exists; resume it rather than fabricate another request')
        record={'schema':1,'request_id':request_id or str(uuid.uuid4()),'nonce':str(uuid.uuid4()),
                'project_root':str(ROOT.resolve()),'turn':turn.relative_to(ROOT).as_posix(),
                'request_sha256':digest((turn/'REQUEST.md').read_bytes()),'authority':authority(),
                'created_at':now(),'status':'ACTIVE','mode':'COOPERATIVE_ENTRYPOINT',
                'host_guarantee':'not verified; this file does not prove the host auto-loaded AGENTS or intercepted every write'}
        if rollback_state is not None:
            pointer=CONTROL/'runtime/runs/current-session.json'
            meta=pointer.with_name(pointer.name+'.apcf-meta.yaml')
            rollback_state.update(binding={k:record[k] for k in ('request_id','turn','project_root')},
                                  before=pointer.read_bytes() if pointer.is_file() else None,
                                  metadata=meta.read_bytes() if meta.is_file() else None)
        private_json(p,record,create=True)
        private_json(CONTROL/'runtime/runs/current-session.json',{'schema':1,'request_id':record['request_id'],'turn':record['turn'],'project_root':record['project_root']})
        return record


def rollback_begin(state):
    """Restore only the pointer still owned by a failed new-Turn invocation."""
    if not state: return
    pointer=CONTROL/'runtime/runs/current-session.json'
    meta=pointer.with_name(pointer.name+'.apcf-meta.yaml')
    with lock(CONTROL/'runtime/tmp/.session.lock'):
        if not pointer.is_file(): return
        current=pointer.read_bytes()
        try: row=json.loads(current)
        except (ValueError,UnicodeError): return
        if any(row.get(k)!=v for k,v in state['binding'].items()): return
        if state['before'] is None:
            pointer.unlink()
        else:
            atomic(pointer,state['before'],expected=current,compare=True)
        if state['metadata'] is None:
            meta.unlink(missing_ok=True)
        else:
            atomic(meta,state['metadata'])


def load(turn, request_id=None):
    turn=_safe_turn(turn)
    row=json.loads((turn/'evidence/execution-session.json').read_text())
    if row.get('schema')!=1 or row.get('project_root')!=str(ROOT.resolve()) or row.get('turn')!=turn.relative_to(ROOT).as_posix():
        raise ValueError('wrong project/worktree/session')
    if request_id is not None and row.get('request_id')!=request_id: raise ValueError('stale request authorization')
    if row.get('request_sha256')!=digest((turn/'REQUEST.md').read_bytes()): raise ValueError('request changed; use recorded scope amendment or a new request')
    pointer=json.loads((CONTROL/'runtime/runs/current-session.json').read_text())
    if any(pointer.get(k)!=row.get(k) for k in ('request_id','turn','project_root')):raise ValueError('another current request superseded this session')
    if row.get('status')!='ACTIVE': raise ValueError('session no longer active')
    if row.get('authority')!=authority(): raise ValueError('authority changed; actual reread and refresh required')
    return row


def resume(turn, request_id):
    row=load(turn,request_id)
    # No assertion about cached model context; list exact files to be reloaded in the host.
    plan=Path(turn)/'evidence/workflow.json'
    return {'session':row,'plan':json.loads(plan.read_text()) if plan.is_file() else None,
            'required_reread':['AGENTS.md','.agent-project-control/interfaces/APCF_ONBOARDING.md',
                               str(Path(turn)/'REQUEST.md'),str(Path(turn)/'CHECKLIST.md'),str(Path(turn)/'TEST.md')],
            'message':'Resume facts, not the old next-step recommendation. Do not repeat confirmed external effects.'}


def refresh(turn, request_id, reason):
    turn=_safe_turn(turn)
    p=turn/'evidence/execution-session.json'
    with lock(CONTROL/'runtime/tmp/.session.lock'):
        old=json.loads(p.read_text())
        pointer=json.loads((CONTROL/'runtime/runs/current-session.json').read_text())
        if old.get('project_root')!=str(ROOT.resolve()) or any(pointer.get(k)!=old.get(k) for k in ('request_id','turn','project_root')):
            raise ValueError('cannot refresh a superseded or foreign session')
        if old.get('request_id')!=request_id or old.get('request_sha256')!=digest((turn/'REQUEST.md').read_bytes()):
            raise ValueError('request mismatch')
        if not reason or not reason.strip(): raise ValueError('refresh requires actual reread reason')
        private_json(turn/'evidence'/('session-refresh-'+uuid.uuid4().hex+'.json'),
                     {'schema':1,'previous':old,'reason':reason,'timestamp':now()},create=True)
        old.update(authority=authority(),nonce=str(uuid.uuid4()))
        private_json(p,old)
        # Existing write ticket binds old authority/session; it must not be silently reused.
        return old


def authorize(turn, request_id):
    from routing_activity import workflow_errors,_contract_digest,file_state
    turn=_safe_turn(turn); row=load(turn,request_id)
    if '- **Status**：IN_PROGRESS' not in (turn/'TURN.md').read_text():raise ValueError('finalized or stopped Turn cannot authorize new writes')
    errors=workflow_errors(turn)
    if errors: raise ValueError('; '.join(errors))
    plan=json.loads((turn/'evidence/workflow.json').read_text())
    ticket={'schema':1,'request_id':row['request_id'],'nonce':row['nonce'],
            'project_root':row['project_root'],'turn':row['turn'],'authority':row['authority'],
            'goal_digest':_contract_digest(turn),'targets':[file_state(p) for p in plan['targets']],
            'sequence':0,'timestamp':now()}
    private_json(turn/'evidence/write-ticket.json',ticket)
    return ticket


def apply_file(turn, request_id, target: str, new_bytes: bytes, before_sha: str | None):
    """CAS-style write of one declared file. Does NOT authorize arbitrary shell commands."""
    from routing_activity import _contract_digest
    turn=_safe_turn(turn)
    with lock(CONTROL/'runtime/tmp/.session.lock'):
        row=load(turn,request_id)
        if '- **Status**：IN_PROGRESS' not in (turn/'TURN.md').read_text():raise ValueError('finalized or stopped Turn cannot write business files')
        p=turn/'evidence/write-ticket.json';ticket=json.loads(p.read_text())
        if (ticket.get('nonce')!=row['nonce'] or ticket.get('request_id')!=request_id or
            ticket.get('goal_digest')!=_contract_digest(turn) or ticket.get('authority')!=authority()):
            raise ValueError('write ticket no longer matches this request/plan/authority')
        path=inside(ROOT,target)
        # This boundary deliberately prevents the writer from authorizing its own framework changes.
        if path.is_relative_to(CONTROL) or target in {'AGENTS.md','CURRENT.md'}:
            raise ValueError('framework/control writes require maintainer deployment, not a business ticket')
        expected=next((x for x in ticket['targets'] if x['path']==target),None)
        if expected is None: raise ValueError('target absent from sealed plan')
        old=path.read_bytes() if path.is_file() else None
        from writing_guard import before_write as writing_before_write
        writing_before_write(turn,target,old)
        actual=digest(old) if old is not None else None
        planned=expected['sha256'] if expected['state']=='file' else None
        if actual!=before_sha or actual!=planned:
            raise ValueError('file changed since authorization; preserve external edits and replan')
        sequence=ticket['sequence']+1
        journal=turn/'evidence'/('write-'+row['nonce']+'-'+str(sequence)+'.json')
        private_json(journal,{'schema':1,'stage':'PREPARED','path':target,'request_id':request_id,
                             'before_sha256':actual,'after_sha256':digest(new_bytes),'timestamp':now()},create=True)
        atomic(path,new_bytes,expected=old,compare=True)
        expected.update(state='file',sha256=digest(new_bytes))
        ticket['sequence']=sequence
        private_json(p,ticket)
        private_json(journal,{'schema':1,'stage':'COMMITTED','path':target,'request_id':request_id,
                             'before_sha256':actual,'after_sha256':digest(new_bytes),'timestamp':now()})
        return digest(new_bytes)


def emit(turn, request_id, output: Path, *, observed=False):
    """Write validated final text. Native chat transport must send this exact artifact."""
    from report_contract import validate_report
    from terminology_review import extract_user_report,read_report_text
    turn=_safe_turn(turn);session=load(turn,request_id)
    text=extract_user_report(read_report_text(turn/'TURN.md'))
    errors=validate_report(text,turn)
    if errors: raise ValueError('; '.join(errors))
    output=Path(output).resolve()
    if output.is_relative_to(CONTROL) and not output.is_relative_to(turn/'evidence'):
        raise ValueError('cannot use another control file as delivery output')
    from writing_guard import enabled as writing_enabled, reader_view
    display=reader_view(text).rstrip() if writing_enabled(turn) else text.rstrip()
    payload=(display+'\n').encode('utf-8')
    if observed:
        if not output.is_file() or normalized(output.read_text(encoding='utf-8-sig')).rstrip()!=normalized(display).rstrip():
            raise ValueError('actual response differs from approved TURN; do not replace it with a fresh summary')
        status='OBSERVED_TEXT_MATCH'
    else:
        if output.exists(): raise ValueError('output already exists; use a fresh output or compare mode')
        from repair_io import exclusive
        exclusive(output,payload);status='PREPARED_FOR_DELIVERY'
    receipt={'schema':1,'status':status,'request_id':session['request_id'],'report_sha256':text_digest(text),
             'output_sha256':digest(output.read_bytes()),'visible_report_sha256':text_digest(display),'timestamp':now(),
             'transport':'not authenticated; compare validates captured text, not an actual user receipt'}
    private_json(turn/'evidence/delivery-text.json',receipt)
    return receipt


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('command',choices=['begin','resume','refresh','authorize','write','prepare-output','compare-output'])
    p.add_argument('--turn',required=True);p.add_argument('--request-id');p.add_argument('--reason')
    p.add_argument('--target');p.add_argument('--input');p.add_argument('--before-sha256');p.add_argument('--output')
    a=p.parse_args()
    try:
        if a.command=='begin':value=begin(a.turn,a.request_id)
        else:
            if not a.request_id:raise ValueError('current request-id is required')
            if a.command=='resume':value=resume(a.turn,a.request_id)
            elif a.command=='refresh':value=refresh(a.turn,a.request_id,a.reason)
            elif a.command=='authorize':value=authorize(a.turn,a.request_id)
            elif a.command=='write':
                if not a.target or not a.input:raise ValueError('--target and --input required')
                value={'sha256':apply_file(a.turn,a.request_id,a.target,Path(a.input).read_bytes(),a.before_sha256)}
            else:
                if not a.output: raise ValueError('--output required')
                value=emit(a.turn,a.request_id,Path(a.output),observed=a.command=='compare-output')
        print(json.dumps(value,ensure_ascii=False,indent=2))
    except (OSError, ValueError, KeyError) as exc:
        print('BLOCKED:',exc);return 2
    return 0

# APCF-REPORT14-ADAPTER v1
from report14.bridge import install as _install_report14
_install_report14('execution_session', globals())

if __name__=='__main__':raise SystemExit(main())
