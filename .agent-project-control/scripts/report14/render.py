# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import copy
import json
import re
from .contract import CONTRACT, SECTIONS, normalize, MAX_BYTES

SCHEMA = {
 '$schema':'https://json-schema.org/draft/2020-12/schema',
 'type':'object','required':['contract_id','sections'],'additionalProperties':False,
 'properties':{'contract_id':{'const':CONTRACT['contract_id']},
 'sections':{'type':'array','minItems':14,'maxItems':14,'prefixItems':[
  {'type':'object','required':['number','body'],'additionalProperties':False,
   'properties':{'number':{'const':i},'body':{'type':'string','maxLength':MAX_BYTES}}} for i in range(1,15)]}}}

def render(model: dict, *, crlf=False) -> str:
    if not isinstance(model,dict) or set(model)!={'contract_id','sections'} or model['contract_id']!=CONTRACT['contract_id']:
        raise ValueError('model contract mismatch')
    rows=model['sections']
    if not isinstance(rows,list) or len(rows)!=14:raise ValueError('model requires14 sections')
    out=[]
    for i,row in enumerate(rows,1):
        if set(row)!={'number','body'} or type(row['number']) is not int or row['number']!=i or not isinstance(row['body'],str):
            raise ValueError('model section mismatch')
        content=normalize(row['body']).strip('\n')
        if len(content.encode('utf-8'))>MAX_BYTES:raise ValueError('body too large')
        out.append(SECTIONS[i]['heading']+'\n\n'+content)
    text='\n\n'.join(out).rstrip()+'\n'
    if len(text.encode('utf-8'))>MAX_BYTES:raise ValueError('model too large')
    return text.replace('\n','\r\n') if crlf else text

def blank_model() -> dict:
    """Unknown is NOT 'none', zero tests, success, or fabricated work."""
    bodies={i:CONTRACT['states']['unknown'] for i in range(1,15)}
    bodies[1]='**结果状态**：\n\n- 本轮目标：当前报告记录本轮已确认的工作与待核实事项\n- 已完成事项：现有记录尚不足以确认具体完成范围\n- 未完成事项：尚需依据实际执行记录核对\n- 整体状态：当前未确认全部交付条件已经满足\n- 动态扩展：'
    bodies[2]='\n\n'.join(f'### 2.{i}. {h}\n\n{v}' for i,(h,v) in enumerate(zip(SECTIONS[2]['subheadings'],[
        '当前尚无足够记录确认此前已完成的工作，已有资料与历史成果不作推测；',
        '本轮按已经提出的任务要求继续整理实际进展，具体范围以原始请求为准；',
        '当前可确认的成果与尚未取得的结果分别记录，未执行事项不写成已经完成；',
        '目前尚未确认全部交付条件满足；后续判断应依据真实工作及验收结果；']),1))
    bodies[10]='### 10.1. 当前可确认范围\n\n现有记录尚不足以支持完整的成果与验收结论；原有文件和已经保存的工作记录仍应保留；后续以实际取得的资料补充，不以推测代替缺失的执行事实；'
    return {'contract_id':CONTRACT['contract_id'],'sections':[{'number':i,'body':bodies[i]} for i in range(1,15)]}

def set_body(model: dict,n: int,text: str):
    model['sections'][n-1]['body']=text
    return model

def record(prefix: str, rid: str, title: str, fs: dict, status: str | None=None) -> str:
    if not re.fullmatch(prefix+r'-\d{2,}',rid) or any(c in title for c in '\n\r【】'):raise ValueError('unsafe record title')
    head='**'+(f'【{status}】' if status else '')+f'【{rid}】【{title}】：**'
    spec=next(s for s in SECTIONS.values() if s.get('prefix')==prefix)
    lines=[head,'']
    for name in spec['fields']:
        if name not in fs:continue
        value=fs[name]
        if isinstance(value,list):
            lines.append('- '+name+'：')
            for j,v in enumerate(value,1):
                marker=f'{j}. ' if spec.get('nested',{}).get(name)=='ordered' else '- '
                chunks=normalize(str(v)).splitlines() or ['']
                lines.append('  '+marker+chunks[0])
                lines += ['  '+' '*len(marker)+x for x in chunks[1:]]
        else:
            chunks=normalize(str(value)).splitlines() or ['']
            lines.append('- '+name+'：'+chunks[0])
            lines += ['  '+x if x else '' for x in chunks[1:]]
        lines.append('')
    return '\n'.join(lines).rstrip()

def from_bodies(bodies: dict[int,str]) -> dict:
    m=blank_model()
    for n,text in bodies.items():set_body(m,n,text)
    return m
