# APCF-META {"schema":1,"visibility":"public"}
"""Bounded repair. Never changes IDs, task status, criteria or arbitrary paths by guess."""
from __future__ import annotations
from dataclasses import dataclass, field
import copy
import json
import re
import subprocess
import os
import signal
import threading
import queue
import tempfile
import time
from pathlib import Path
from .contract import CONTRACT, SECTIONS, MAX_BYTES, guidance, normalize, sha
from .markdown import parse, body, records
from .render import blank_model, render
from .validate import validate

PROMPT = '''只修复所列授权区间；输出 JSON {"report_sha256":"...","edits":[{"start":0,"end":1,"old_sha256":"...","replacement":"..."}]}；行号零起点，end不包含；不得修改其他区间、任务编号、已确定状态、原定要求或验收标准；约束和案例仅指导写法，事实只来自当前记录；缺少事实时保留未知，不复制教学数值或路径；只返回JSON，不执行代码或外部操作；'''

@dataclass
class Outcome:
    text: str
    mode: str
    attempts: int
    diagnostics: list = field(default_factory=list)
    content_verified: bool = False
    business_complete: bool = False


def deterministic(text: str, context=None) -> str:
    """Structural normalization only; no global unescaping of user Windows paths."""
    text=normalize(text)
    doc=parse(text)
    # Existing well-formed headings can be reordered. Duplicate or ambiguous IDs cannot.
    if len({s.number for s in doc.sections})==len(doc.sections) and all(1<=s.number<=14 for s in doc.sections):
        bodies={s.number:body(doc,s) for s in doc.sections}
        model=blank_model()
        for n,b in bodies.items():model['sections'][n-1]['body']=b
        # Only recover missing structure from a separately supplied trusted baseline.
        for n,b in context.get('safe_bodies',{}).items() if context else []:
            if int(n) not in bodies:model['sections'][int(n)-1]['body']=b
        # Do not insert unknown sections as a 'normal' repair when task coverage requires data.
        text=render(model)
    return _safe_edits(text)

def _safe_edits(text: str) -> str:
    doc=parse(text); edits=[]
    for section in doc.sections:
        spec=SECTIONS.get(section.number,{})
        if spec.get('kind')!='records': continue
        rs,orphans=records(section)
        for rec in rs:
            if len(rec['parts']) not in (2,3): continue
            names=[f['name'] for f in rec['fields']]
            if len(names)!=len(set(names)): continue
            if '动态扩展' not in names and names and all(n in spec['fields'] for n in names):
                # Empty optional body is permitted; do not fill a missing fact.
                end=rec['end']
                while end>rec['line'] and not doc.lines[end-1].strip(): end-=1
                edits.append((end,end,'\n- 动态扩展：\n'))
            for f in rec['fields']:
                if spec.get('nested',{}).get(f['name'])=='sources' and f['value'] and not f['lists']:
                    if re.fullmatch(r'`[^`]+`：[^\n]+',f['value']):
                        edits.append((f['line'],f['end'],'- 证据来源：\n  - '+f['value']+'\n'))
    lines=doc.lines[:]
    for a,b,value in sorted(edits,reverse=True):lines[a:b]=[value]
    return ''.join(lines)

def jobs(text: str, result, context: dict) -> dict:
    lines=normalize(text).splitlines(keepends=True)
    doc=parse(text); ranges=[]
    for f in result.findings:
        if f.severity!='error':continue
        s=next((s for s in doc.sections if s.number==f.section),None)
        a,b=f.line,f.end_line
        if f.code in ('R14-SECTIONS','R14-PARSE','R14-PREFIX'):
            # No whole-document LLM rewrite for structure; deterministic fallback handles this.
            continue
        if f.code in ('R14-STATUS','R14-ID','R14-ID-DUPLICATE','R14-IMMUTABLE','R14-STATUS-BINDING'):
            # Protected facts can only be restored from canonical source, not regenerated.
            continue
        if not s:continue
        if f.code=='R14-FIELD-MISSING' and f.field:
            rs,_=records(s)
            rec=next((r for r in rs if len(r['parts'])>=2 and r['parts'][-2]==f.record),None)
            order=SECTIONS[s.number].get('fields',[])
            if rec and f.field in order:
                later=[v for v in rec['fields'] if v['name'] in order and order.index(v['name'])>order.index(f.field)]
                a=later[0]['line'] if later else rec['end']
                if not later:
                    while a>rec['line'] and not lines[a-1].strip():a-=1
                b=a
        a=max(s.body_line,a);b=min(s.end,max(b,a))
        g=guidance(s.number, f.field or None)
        ranges.append({'start':a,'end':b,'old_sha256':sha(''.join(lines[a:b])),
                       'diagnostic':f.json(),'guidance':g})
    # Merge overlapping scopes only; preserve all constraint snippets in batched job.
    merged=[]
    for r in sorted(ranges,key=lambda x:(x['start'],x['end'])):
        if merged and (r['start']<merged[-1]['end'] or r['start']==r['end']==merged[-1]['start']==merged[-1]['end']):
            q=merged[-1];q['end']=max(q['end'],r['end']);q['rules'].append(r)
            q['old_sha256']=sha(''.join(lines[q['start']:q['end']]))
        else:merged.append({'start':r['start'],'end':r['end'],'old_sha256':r['old_sha256'],'rules':[r]})
    for q in merged:
        q['current']=''.join(lines[q['start']:q['end']])
        q['before']=''.join(lines[max(0,q['start']-3):q['start']])
        q['after']=''.join(lines[q['end']:q['end']+3])
    return {'schema':1,'instruction':PROMPT,'report_sha256':sha(normalize(text)),
            'allowed_ranges':merged,'facts':context.get('agent_facts',{}),
            'record_bindings':context.get('records',{}),'external_records':context.get('external_records',{})}

def apply_edits(text: str, response: dict, job: dict) -> str:
    text=normalize(text); lines=text.splitlines(keepends=True)
    if not isinstance(response,dict) or set(response)!={'report_sha256','edits'} or response['report_sha256']!=sha(text):
        raise ValueError('stale or malformed edit response')
    edits=response['edits']; allowed={(x['start'],x['end'],x['old_sha256']) for x in job['allowed_ranges']}
    if not isinstance(edits,list) or len(edits)>len(allowed):raise ValueError('edit count')
    prev=-1
    for e in sorted(edits,key=lambda x:x.get('start',-1)):
        if set(e)!={'start','end','old_sha256','replacement'} or type(e['start']) is not int or type(e['end']) is not int:raise ValueError('edit shape')
        if (e['start'],e['end'],e['old_sha256']) not in allowed or e['start']<prev:raise ValueError('scope violation')
        if e['old_sha256']!=sha(''.join(lines[e['start']:e['end']])):raise ValueError('preimage mismatch')
        if not isinstance(e['replacement'],str) or len(e['replacement'].encode())>MAX_BYTES:raise ValueError('edit content')
        if parse(e['replacement']).sections:raise ValueError('repair cannot inject main headings')
        prev=e['end']
    for e in sorted(edits,key=lambda x:x['start'],reverse=True):
        lines[e['start']:e['end']]=[normalize(e['replacement'])]
    return ''.join(lines)

_SLOTS=threading.BoundedSemaphore(4)

def call_agent(agent,job,timeout):
    # A host callback must not stall the main delivery thread. Timed-out calls are
    # abandoned; at most four stuck callbacks can exist. Real command adapters also
    # terminate their own isolated worker process/group.
    if not _SLOTS.acquire(blocking=False):raise TimeoutError('repair workers busy')
    q=queue.Queue(maxsize=1)
    def run():
        try:q.put((True,agent(job,timeout)))
        except BaseException as exc:q.put((False,exc))
        finally:_SLOTS.release()
    threading.Thread(target=run,daemon=True).start()
    try:ok,value=q.get(timeout=max(.01,timeout)+(.25 if isinstance(agent,CommandAgent) else 0))
    except queue.Empty:raise TimeoutError('repair deadline')
    if ok:return value
    raise value if isinstance(value,Exception) else RuntimeError('worker interrupted')

class CommandAgent:
    """One isolated worker per call, no shell, timeout and bounded readback.

    Worker must treat stdin as a JSON request and print only a JSON edits response.
    No executor is selected implicitly. Host supplies an already-authorized command.
    """
    def __init__(self, command: list[str], cwd: str | None=None):
        if not command or not all(isinstance(v,str) and v for v in command):raise ValueError('command required')
        self.command=command;self.cwd=cwd
    def __call__(self,job:dict,timeout:float)->dict:
        with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as log:
            proc=subprocess.Popen(self.command,cwd=self.cwd,stdin=subprocess.PIPE,stdout=output,stderr=log,shell=False,
                start_new_session=os.name!='nt', creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
            try:proc.communicate(json.dumps(job,ensure_ascii=False).encode('utf8'),timeout=max(.01,timeout))
            except subprocess.TimeoutExpired:
                if os.name=='nt':
                    try:subprocess.run(['taskkill','/PID',str(proc.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2)
                    except Exception:proc.kill()
                else:
                    try:os.killpg(proc.pid,signal.SIGKILL)
                    except ProcessLookupError:pass
                proc.communicate(timeout=2)
                raise TimeoutError('agent timeout')
            if proc.returncode:raise RuntimeError('agent worker failed')
            size=output.tell()
            if size>MAX_BYTES:raise ValueError('worker output too large')
            output.seek(0);return json.loads(output.read().decode('utf-8'))

def safe_fallback(text: str, context:dict, result) -> str:
    """Retain valid sections; replace only affected content with verified baseline.

    Complete baseline is preferred. Unknown never silently becomes no work or PASS.
    An unrecoverable draft remains in the private diagnostic archive, not in output.
    """
    baseline=copy.deepcopy(context.get('safe_model') or blank_model())
    base_text=render(baseline)
    base_context=context.get('safe_context',{})
    if not validate(base_text,base_context).ok:
        # Misconfigured authority is not allowed to leak an invalid report.
        baseline=blank_model();base_context={}
    try:
        doc=parse(text)
        bad={f.section for f in result.findings if f.severity=='error'}
        if 0 not in bad:
            for s in doc.sections:
                if s.number not in bad and 1<=s.number<=14:
                    baseline['sections'][s.number-1]['body']=body(doc,s)
    except Exception:pass
    candidate=render(baseline)
    merged_check=validate(candidate,base_context)
    if merged_check.ok:return candidate
    # References can depend on an edited section: restore the coherent source snapshot,
    # not arbitrary records from an older or unrelated task.
    original=context.get('safe_model')
    if original is not None:
        candidate=render(original)
        if validate(candidate,base_context).ok:return candidate
    return render(blank_model())

def deliver(draft: str, context: dict | None=None, agent=None, *, max_rounds=2, budget_seconds=35.0) -> Outcome:
    context=context or {};logs=[];attempts=0;deadline=time.monotonic()+max(0,min(budget_seconds,120.0))
    original=draft if isinstance(draft,str) else ''
    text=original
    try:
        first=validate(text,context);logs.append({'phase':'initial','result':first.json(),'sha256':sha(text)})
        if first.ok:return Outcome(text,'unchanged',0,logs)
        text=deterministic(text,context)
        check=validate(text,context);logs.append({'phase':'deterministic','result':check.json(),'sha256':sha(text)})
        if check.ok:return Outcome(text,'deterministic',0,logs)
        for i in range(min(2,max(0,int(max_rounds)))):
            remaining=deadline-time.monotonic()
            if agent is None or remaining<=0:break
            job=jobs(text,check,context)
            if not job['allowed_ranges']:break
            attempts+=1;before=text
            try:
                response=call_agent(agent,job,remaining)
                candidate=apply_edits(text,response,job)
                new=validate(candidate,context)
                # Any immutable-record drift rejects the response as a whole.
                if any(f.code in ('R14-IMMUTABLE','R14-STATUS-BINDING') for f in new.findings):raise ValueError('protected fact changed')
                text=candidate;check=new
                logs.append({'phase':'agent','round':attempts,'job':job,'response':response,
                             'before_sha256':sha(before),'after_sha256':sha(text),'result':check.json()})
                if check.ok:return Outcome(text,'agent',attempts,logs)
                if text==before:break
            except Exception as exc:
                logs.append({'phase':'agent','round':attempts,'internal_error':type(exc).__name__})
                if isinstance(exc,TimeoutError):break
        output=safe_fallback(text,context,check)
        logs.append({'phase':'fallback','rejected_draft':original,'result':validate(output,context.get('safe_context',{})).json()})
        return Outcome(output,'fallback',attempts,logs)
    except Exception as exc:
        # Outermost in-process safety net: no traceback, validator message or teaching text.
        logs.append({'phase':'recovery','internal_error':type(exc).__name__})
        try: output=render(context.get('safe_model') or blank_model())
        except Exception:output=render(blank_model())
        try:
            if not validate(output,context.get('safe_context',{})).ok:output=render(blank_model())
        except Exception:output=render(blank_model())
        return Outcome(output,'fallback',attempts,logs)
