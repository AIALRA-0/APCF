# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import copy, json, os, signal, subprocess, time
from .contract import Issue,validate,digest,ContractError
from .quality import assess


def get_pointer(obj,pointer):
    cur=obj
    for key in pointer.strip('/').split('/'):
        key=key.replace('~1','/').replace('~0','~');cur=cur[int(key)] if isinstance(cur,list) else cur[key]
    return cur

def set_pointer(obj,pointer,value):
    keys=pointer.strip('/').split('/');cur=obj
    for key in keys[:-1]:cur=cur[int(key)] if isinstance(cur,list) else cur[key]
    key=keys[-1];cur[int(key) if isinstance(cur,list) else key]=value


def apply_patch(base:dict,response:dict,allowed:set[str])->dict:
    if response.get('base_digest')!=digest(base):raise ContractError('STALE_REPAIR')
    changes=response.get('changes')
    if not isinstance(changes,list) or not changes:raise ContractError('EMPTY_REPAIR')
    result=copy.deepcopy(base);seen=set()
    for ch in changes:
        path=ch.get('pointer','')
        if path not in allowed or path in seen:raise ContractError('REPAIR_SCOPE')
        seen.add(path)
        before=get_pointer(base,path)
        if ch.get('before_digest')!=digest(before):raise ContractError('STALE_FIELD')
        if not isinstance(ch.get('value'),str):raise ContractError('TEXT_ONLY_REPAIR')
        # The caller constructs allowed paths from narrative fields, never machine facts.
        set_pointer(result,path,ch['value'])
    return result


def model_command(command:list[str],payload:dict,timeout_seconds:float)->dict:
    if not command or not all(isinstance(x,str) for x in command):raise ContractError('INVALID_AGENT_COMMAND')
    kwargs={'stdin':subprocess.PIPE,'stdout':subprocess.PIPE,'stderr':subprocess.PIPE,'text':True,'encoding':'utf-8'}
    if os.name!='nt':kwargs['start_new_session']=True
    else:kwargs['creationflags']=subprocess.CREATE_NEW_PROCESS_GROUP
    proc=subprocess.Popen(command,**kwargs)
    try:out,err=proc.communicate(json.dumps(payload,ensure_ascii=False),timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],capture_output=True,timeout=5)
        else:os.killpg(proc.pid,signal.SIGKILL)
        proc.communicate();raise ContractError('AGENT_TIMEOUT')
    if proc.returncode:raise ContractError('AGENT_NONZERO') # stderr only to protected internal diagnostics
    if len(out)>2_000_000:raise ContractError('AGENT_RESPONSE_TOO_LARGE')
    return json.loads(out)


def repair(snapshot:dict,agent,context_resolver,*,max_rounds=2,deadline_seconds=90,semantic_reviewer=None,projection_checker=None)->dict:
    """Bounded orchestrator: report availability is distinct from quality PASS.

    agent(request, remaining_seconds) and reviewer must honor the deadline; use
    model_command for subprocess adapters. No indefinite threads are created.
    """
    current=copy.deepcopy(snapshot);history=[];deadline=time.monotonic()+deadline_seconds
    for sec in current.get('sections',[]):
        for rec in sec.get('records',[]):
            for field in rec.get('locked',{}):
                if field in ['行动要求','验收标准','预期结果']:
                    rec.setdefault('explanations',{}).setdefault(field,'')
    for turn in range(min(max_rounds,2)+1):
        structural=validate(current);quality=assess(current)
        semantic=[]
        semantic_complete=False
        if semantic_reviewer and not [i for i in structural if i.severity=='error']:
            remaining=deadline-time.monotonic()
            if remaining>0:
                try:
                    semantic=semantic_reviewer(current,remaining)
                    semantic_complete=semantic==[]
                except Exception as exc:
                    history.append({'stage':'review','error_type':type(exc).__name__})
                    semantic=[Issue('REVIEW_UNAVAILABLE','/','内容复核尚未完成','review')]
        if semantic_complete:
            discharged=[i for i in quality if i.code in ('QUALITY_SHORT','QUALITY_EXPLANATION_SHORT')]
            if discharged:history.append({'stage':'probe_disposition','basis':'same-snapshot independent role review','pointers':[i.pointer for i in discharged]})
            quality=[i for i in quality if i.code not in ('QUALITY_SHORT','QUALITY_EXPLANATION_SHORT')]
        projection=projection_checker(current) if projection_checker else []
        problems=structural+quality+semantic+projection
        if not problems:
            return {'report':current,'quality':'reviewed' if semantic_reviewer else 'unreviewed',
                    'structure':'valid','history':history,'rounds':turn}
        if turn>=min(max_rounds,2) or time.monotonic()>=deadline:break
        allowed=set();targets=[]
        for issue in problems:
            ptr=issue.pointer
            if '/subsections/' in ptr and ptr.count('/')==4:
                ptr += '/paragraphs/0'
            if not any(x in ptr for x in ('/fields/','/explanations/','/paragraphs/','/description','/chat/')):continue
            try:old=get_pointer(current,ptr)
            except (KeyError,IndexError,ValueError,TypeError):continue
            if not isinstance(old,str):continue
            # Commitments must stay immutable. A separate explanation may be authored
            # by the initial writer, not by a repair that changes acceptance criteria.
            field=ptr.rsplit('/',1)[-1]
            if '/fields/' in ptr:
                # Header group fields are native facts, never repair targets.
                if '/records/' not in ptr:continue
                bits=ptr.strip('/').split('/');rec=current['sections'][int(bits[1])]['records'][int(bits[3])]
                if field in rec.get('locked',{}) or field in ['行动要求','验收标准','预期结果','关联记录','关联证据']:continue
            allowed.add(ptr)
            targets.append({'pointer':ptr,'before_digest':digest(old),'text':old,'issue':issue.to_dict(),
                            'guidance':context_resolver(ptr,current)})
        if not targets or agent is None:break
        request={'kind':'local-repair','base_digest':digest(current),'source_digest':current['source_digest'],
                 'targets':targets,'instructions':'仅返回授权字段的新解释；不得更改状态、数量、路径、身份、事实、判据或权限。没有事实依据时返回事实缺口，不得模仿案例编造。'}
        try:
            response=agent(request,max(.01,deadline-time.monotonic()))
            updated=apply_patch(current,response,allowed)
            # Never regress structural validity. All mutable fields are still audited.
            prior={(x.code,x.pointer) for x in structural if x.severity=='error'}
            now={(x.code,x.pointer) for x in validate(updated) if x.severity=='error'}
            if now-prior:raise ContractError('REPAIR_REGRESSION')
            history.append({'round':turn+1,'base_digest':digest(current),'after_digest':digest(updated),'changed':[x['pointer'] for x in response['changes']],'result':'applied'})
            current=updated
        except Exception as exc:history.append({'round':turn+1,'result':'retained','error_type':type(exc).__name__})
    final=validate(current)
    return {'report':current,'quality':'needs_review','structure':'invalid' if any(x.severity=='error' for x in final) else 'valid',
            'history':history,'rounds':len([x for x in history if 'round' in x]),
            'issues':[x.to_dict() for x in final+assess(current)+(projection_checker(current) if projection_checker else [])]}
