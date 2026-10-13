# APCF-META {"schema":1,"visibility":"public"}
"""Read-only projections from native ledgers. Never write CHECKLIST/TEST or infer evidence."""
from __future__ import annotations
import json
import re
from pathlib import Path
from .contract import normalize, sha
from .markdown import parse, records, body
from .render import blank_model, render, set_body, record
from .validate import validate

TURN_MARKER='## 1.1. USER REPORT'
CURRENT_MARKER='## 1.1. 最新完整用户报告'
META=re.compile(r'<!-- APCF-REPORT14 ([^\n]+) -->')

def report_text(text: str) -> str:
    text=normalize(text)
    if TURN_MARKER in text:return text.split(TURN_MARKER,1)[1].strip()+'\n'
    if CURRENT_MARKER in text:return text.split(CURRENT_MARKER,1)[1].strip()+'\n'
    m=re.search(r'^## 1\. 精确状态头\s*$',text,re.M)
    return text[m.start():].strip()+'\n' if m else text.strip()+'\n'

def is14(text: str) -> bool:
    return bool(re.search(r'^## 1\. 精确状态头\s*$',normalize(text),re.M))

def published_meta(text: str) -> dict:
    m=META.search(normalize(text))
    if not m:return {}
    row=json.loads(m[1])
    if row.get('schema')!=1 or row.get('report_sha256')!=sha(report_text(text)):
        raise ValueError('report presentation binding mismatch')
    return row

def current_bytes(report: str, source: str | None, request_id='', *, kind='checkpoint') -> bytes:
    report=normalize(report).strip()+'\n'
    row={'schema':1,'source_turn':source,'request_id':request_id,'kind':kind,'report_sha256':sha(report)}
    # Native regex readers can retain Source TURN without adding visible chapters.
    meta='<!-- APCF-META {"schema":1,"visibility":"public"} -->\n<!-- APCF-REPORT14 '+json.dumps(row,ensure_ascii=False,separators=(',',':'))+' -->\n'
    if source:
        if any(c in source for c in '\r\n`<>'):raise ValueError('unsafe source identity')
        meta+='<!-- APCF-CURRENT-SOURCE\n- **Source TURN**：`'+source+'`\n-->\n'
    else:meta+='<!-- APCF-INITIAL - **Latest TR**：不适用；尚未开始项目执行轮次 -->\n'
    return (meta+report).replace('\n','\r\n').encode('utf-8')

def _spans(row:dict,name:str,default=''):
    v=row.get(name)
    if isinstance(v,str) and v.strip():return v
    spans=row.get('_spans',{})
    pair=spans.get(name);text=row.get('_prose',row.get('body',''))
    return text[pair[0]:pair[1]] if isinstance(pair,list) and len(pair)==2 else default

def _safe(value):
    # Preserve text, but prevent a source line from injecting report structure.
    return normalize(str(value)).replace('\n','；').strip() or '现有记录尚未提供此项信息'

def safe_turn(root:Path,turn:Path) -> Path:
    """Normalize Windows aliases while retaining the native link/reparse boundary."""
    from repair_io import inside,linked
    root=Path(root).resolve();candidate=Path(turn).absolute()
    if any(linked(p) for p in (candidate,*candidate.parents)):
        raise ValueError('unsafe Turn link/reparse path')
    raw=candidate.resolve().relative_to(root).as_posix()
    if not raw.startswith('.agent-project-control/iterations/'):
        raise ValueError('wrong Turn location')
    return inside(root,raw)

def load_context(root:Path,turn:Path) -> dict:
    from repair_io import inside
    root=root.resolve(); turn=safe_turn(root,turn);raw=turn.relative_to(root).as_posix()
    turn=inside(root,raw)
    if not turn.is_dir() or not turn.is_relative_to(root/'.agent-project-control/iterations'):
        raise ValueError('wrong Turn location')
    snapshots={};texts={}
    for name in ('REQUEST.md','CHECKLIST.md','TEST.md'):
        p=inside(root,raw+'/'+name)
        if p.is_file():
            data=p.read_bytes();snapshots[p.relative_to(root).as_posix()]=sha(data);texts[name]=data.decode('utf-8-sig')
    model=blank_model(); bindings={};external={}; notes=[]
    # Native parser accepts approved v1/v2/v3 source forms with their own hash checks.
    from test_ledger import parse_checklist,parse_tests
    cls=parse_checklist(texts.get('CHECKLIST.md',''));tests=parse_tests(texts.get('TEST.md',''))
    projected=[]
    for row in cls:
        rid=row['id'];status=row['status'];title=row['object']
        if not re.fullmatch(r'CL-\d{2,}',rid):notes.append('现有任务编号 '+rid+' 尚需按原始身份完成兼容核对');continue
        external[rid]={'status':status,'source':'CHECKLIST.md'}
        if status=='不适用':notes.append(rid+' 在现有任务清单中记为不适用，未计入本轮执行项');continue
        rendered_status=status if status in ('已完成','失败','阻塞') else '失败'
        action=_safe(_spans(row,'requirement',row.get('body','')))
        criterion=_safe(_spans(row,'criterion','现有清单未单独拆出验收标准；以原始约定为准，尚需核对'))
        fs={'任务缘由':_safe(_spans(row,'problem',row.get('body',''))),
            '行动要求':action,'风险说明':'沿用原任务的保护要求；现有清单未单独拆分的风险内容不作推测',
            '验收标准':criterion,
            '执行结果':('原生任务清单记录状态为'+status+'；此处保留其已登记的进展，不将报告整理视为重新执行或重新验收'),
            '动态扩展':''}
        if rendered_status in ('失败','阻塞'):
            fs[rendered_status+'原因']=('现有任务清单记录为'+status+'，原定工作尚未形成完整达标结论；具体业务原因需依原有调查和执行记录确认，不据此推断产品发生故障')
            fs['处理建议']='由执行方继续读取原始请求与已有调查，完成权限范围内仍可推进的原定工作，并按原标准验收；必要的外部条件应按真实缺口单独确认'
        projected.append(record('CL',rid,title,fs,rendered_status))
        bindings[rid]={'section':4,'status':rendered_status,'immutable_fields':{'行动要求':action,'验收标准':criterion}}
    if projected:
        cnt={s:sum(v['status']==s for v in bindings.values()) for s in ('已完成','失败','阻塞')}
        overview='**执行总览**：CL 总数：'+str(len(projected))+'；'+'；'.join(k+'：'+str(v) for k,v in cnt.items())
        set_body(model,4,overview+'\n\n'+'\n\n'.join(projected))
    elif cls and len(notes)==len(cls):set_body(model,4,'本轮不适用：现有清单中的事项均不属于本轮执行范围')
    projected=[]; tcounts={s:0 for s in ('通过','失败','阻塞','未执行')}
    for row in tests:
        rid=row['id'];status={'PASS':'通过','FAIL':'失败','BLOCKED':'阻塞','进行中':'未执行'}.get(row['status'],row['status'])
        if not re.fullmatch(r'TEST-\d{2,}',rid) or status not in tcounts:continue
        refs=row.get('refs',[]); refs=[r for r in refs if r in external]
        expected=_safe(_spans(row,'expected'))
        actual=_safe(_spans(row,'actual'))
        fs={'对应任务':'、'.join(refs) or '当前源账本的对应任务尚需核对',
            '验收方式':_safe(_spans(row,'context'))+'；'+_safe(_spans(row,'action')),
            '预期结果':expected,'实际结果':actual,'关联证据':_safe(_spans(row,'evidence')),'动态扩展':''}
        if row['status']=='进行中':fs['动态扩展']='原生验收仍在执行中，此处未执行指最终验收尚未完成；已发生的检查保留在实际结果中'
        if status in ('失败','阻塞'):
            fs[status+'原因']='现有验收记录显示：'+actual+'；已核实的具体原因以原始调查材料为准'
            fs['处理建议']='由执行方沿用本项输入、判据和原始证据继续核查，完成实际修复或取得必要条件后重新验收；保留本次结果'
        projected.append(record('TEST',rid,row['object'],fs,status));tcounts[status]+=1
        external[rid]={'status':status,'source':'TEST.md'}
        bindings[rid]={'section':6,'status':status,'immutable_fields':{'预期结果':expected,'实际结果':actual}}
    if projected:set_body(model,6,'**验收总览**：TEST 总数：'+str(len(projected))+'；'+'；'.join(k+'：'+str(v) for k,v in tcounts.items())+'\n\n'+'\n\n'.join(projected))
    # Add existing canonical EV definitions, never IDs from the educational reference.
    ev_file=inside(root,raw+'/EVIDENCE.md')
    if ev_file.is_file():
        snapshots[ev_file.relative_to(root).as_posix()]=sha(ev_file.read_bytes())
        for rid in re.findall(r'^\*\*【(EV-\d{2,})】',ev_file.read_text(encoding='utf-8-sig'),re.M):external[rid]={'source':'EVIDENCE.md'}
    # Record unavailable mapping as real scope limitations rather than zero work.
    if notes:
        set_body(model,1,'**补充说明**：\n\n- 额外重要事实：'+'；'.join(notes)+'\n- 单独说明原因：保留原有任务身份与适用范围\n- 实际影响：未核对的兼容关系不纳入完成结论\n- 动态扩展：')
    context={'records':bindings,'external_records':external,'source_hashes':snapshots,
             'record_sets':{p:[rid for rid in bindings if rid.startswith(p+'-')] for p in ('CL','TEST')},
             'agent_facts':{'request':texts.get('REQUEST.md','')[:12000], 'ledgers':texts},
             'safe_model':model}
    # Native conflicts stay a business limitation; fallback reflects native actuals.
    safe_context={'external_records':external}
    context['safe_context']=safe_context
    result=validate(render(model),safe_context)
    if not result.ok:
        # Do not drop source facts to gain a green checkbox. Preserve the exact ledger
        # text as quoted material in a prose section, and explicitly leave summaries unknown.
        model=blank_model()
        text='### 10.1. 已取得的原始任务与验收记录\n\n当前记录尚需完成对应关系核对，暂不据此确认全部任务达标；以下保留已有内容，未额外补造任务或测试结果；\n\n'
        for name in ('CHECKLIST.md','TEST.md'):
            if texts.get(name):
                raw_text=texts[name].replace('```','` ` `')
                text+='**'+name+'**\n\n```text\n'+raw_text+'\n```\n\n'
        set_body(model,10,text)
        # Template metadata and original placeholders cannot leak: keep unknown on conflicts.
        if not validate(render(model)).ok:model=blank_model()
        context['safe_model']=model;context['safe_context']={}
    return context

def unchanged(root:Path,snapshot:dict) -> bool:
    from repair_io import inside
    return all((p:=inside(root,k)).is_file() and sha(p.read_bytes())==v for k,v in snapshot.items())
