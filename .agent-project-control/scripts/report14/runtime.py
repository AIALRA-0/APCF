# APCF-META {"schema":1,"visibility":"public"}
"""Single non-streaming delivery boundary; user transport receives only the final report."""
from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from .contract import normalize,sha
from .bindings import load_context,report_text
from .render import render,blank_model,set_body
from .repair import deliver,CommandAgent
from .storage import Store
from .validate import validate

@dataclass
class Delivery:
    report: str
    saved: bool
    mode: str
    attempts: int
    diagnostics: list
    chat: str = ''
    quality: str = 'needs_review'
    binding: dict | None = None
    def receipt(self):return {'schema':1,'report_sha256':sha(normalize(self.report).strip()+'\n'),
        'saved':self.saved,'format_valid':validate(self.report).ok,'mode':self.mode,'repair_rounds':self.attempts,
        'business_complete':False,'semantic_quality':self.quality}

def agent_from_config(root):
    p=Path(root)/'.agent-project-control/reporting/agent.local.json'
    if not p.is_file():return None
    config=json.loads(p.read_text('utf-8'))
    if config.get('enabled') is not True:return None
    # Command is administrator configuration; it is NEVER taken from draft/model text.
    return CommandAgent(config['command'],str(root))

def archive_note(text):
    from .markdown import body_model
    try:
        m=body_model(text);current=m['sections'][0]['body']
        note='本轮报告已整理；项目档案同步尚未确认，暂不据此认定正式归档完成'
        if '**补充说明**：' in current:
            # Preserve existing facts and place note in its last dynamic field.
            start=current.index('**补充说明**：');head=current[:start];tail=current[start:]
            if '- 动态扩展：' in tail:tail=tail.replace('- 动态扩展：','- 动态扩展：'+note+'；',1)
            current=head+tail
        else:current+='\n\n**补充说明**：\n\n- 额外重要事实：'+note+'\n- 单独说明原因：正文交付与项目档案保存分别核对\n- 实际影响：当前不确认项目档案已经更新\n- 动态扩展：'
        set_body(m,1,current);out=render(m)
        return out if validate(out).ok else text
    except Exception:return text

def _legacy_publish(root:Path,turn:Path,draft:str|None=None,*,request_id='',agent=None,max_rounds=2,budget_seconds=35,store=None) -> Delivery:
    root=Path(root).resolve();turn=Path(turn).absolute();store=store or Store(root)
    logs=[];context={};oldcurrent=oldturn=None;can_save=False
    try:
        # Recovery is bounded; no lock is held while generating or repairing text.
        store.recover()
        context=load_context(root,turn)
        oldturn=(turn/'TURN.md').read_bytes()
        oldcurrent=(root/'CURRENT.md').read_bytes() if (root/'CURRENT.md').exists() else None
        if request_id:
            import execution_session
            execution_session.load(turn,request_id)
        can_save=True
    except Exception as exc:logs.append({'phase':'source','error':type(exc).__name__})
    if draft is None:
        try:draft=report_text((oldturn or b'').decode('utf-8-sig'))
        except Exception:draft=''
    try:
        if agent is None:agent=agent_from_config(root)
    except Exception as exc:logs.append({'phase':'adapter','error':type(exc).__name__});agent=None
    outcome=deliver(draft,context,agent,max_rounds=max_rounds,budget_seconds=budget_seconds)
    logs+=outcome.diagnostics;saved=False
    if can_save:
        try:
            result=store.publish(turn,outcome.text,request_id=request_id,sources=context.get('source_hashes',{}),
                                 before_current=oldcurrent,before_turn=oldturn)
            saved=result['saved'];logs.append({'phase':'persistence',**result})
        except Exception as exc:
            logs.append({'phase':'persistence','error':type(exc).__name__})
            try:store.recover()
            except Exception:pass
    text=outcome.text if saved else archive_note(outcome.text)
    store.audit({'diagnostics':logs,'source_hashes':context.get('source_hashes',{}),'saved':saved})
    return Delivery(text,saved,outcome.mode,outcome.attempts,logs)


def publish(root:Path,turn:Path,draft=None,*,request_id='',agent=None,max_rounds=2,budget_seconds=90,store=None) -> Delivery:
    """Current writes always pass the native typed-source boundary."""
    from report_bridge.ports import publish as native_publish,prepared
    try:
        if not request_id:
            request_id=json.loads((Path(turn)/'evidence/execution-session.json').read_text('utf-8-sig'))['request_id']
        result=prepared(root,turn,request_id) if draft is None and (Path(turn)/'evidence/report-quality-delivery.json').is_file() else native_publish(root,turn,draft,request_id=request_id,budget_seconds=budget_seconds)
        repair_result=result.get('repair',{})
        return Delivery(result['report'],True,'typed_native',repair_result.get('rounds',0),repair_result.get('history',[]),result['chat'],result['quality'],result['receipt'])
    except Exception as exc:
        Store(Path(root)).audit({'phase':'typed_public_boundary','error_type':type(exc).__name__})
        text='本轮已有工作与执行记录继续保留；本次报告更新尚未确认保存，未完成事项保持原状态\n\n完整记录见当前项目的 `CURRENT.md`\n'
        return Delivery('',False,'available_progress',0,[{'error_type':type(exc).__name__}],text,'needs_review')

def transport(root,turn,draft,sink,*,request_id='',agent=None,message_kind='formal_report'):
    """Host adapter: buffer internally, render/repair/persist, then call the real sink once.

    No model may rewrite the payload after this call. Sink availability is a host/OS
    property; this function does not claim to survive power loss or a dead transport.
    """
    if message_kind=='ordinary_reply':
        sink(draft);return {'formal_report':False,'sent_to_sink':True}
    if message_kind!='formal_report':raise ValueError('host must classify message kind')
    delivery=publish(root,turn,draft,request_id=request_id,agent=agent)
    receipt=delivery.receipt()
    try:
        import inspect
        try:inspect.signature(sink).bind(delivery.chat,delivery.binding);supports_binding=True
        except (TypeError,ValueError):supports_binding=False
        if supports_binding:
            sink(delivery.chat,delivery.binding);receipt['host_binding_sent']=True
        else:
            sink(delivery.chat);receipt['host_binding_sent']=False
        receipt['sent_to_sink']=True
        receipt['host_scope']='caller sink; actual capture still required' if supports_binding else 'cooperative text only; identity capture unverified'
    except Exception as exc:
        Store(Path(root)).audit({'phase':'transport','internal_error':type(exc).__name__})
        receipt['sent_to_sink']=False
    return receipt
