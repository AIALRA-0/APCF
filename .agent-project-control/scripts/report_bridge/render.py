# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import re
from .contract import TITLES,FIELDS,PREFIX,STATES,FILE_TYPES,validate,ContractError


def line_text(value):
    return str(value).replace('\r\n','\n').replace('\r','\n').strip()

def field_line(label,text):
    lines=line_text(text).split('\n')
    return '- '+label+'：'+lines[0]+''.join('\n  '+x for x in lines[1:])

def render(snapshot:dict)->str:
    errors=[x for x in validate(snapshot) if x.severity=='error']
    if errors:raise ContractError(';'.join(x.code+':'+x.pointer for x in errors))
    chunks=[]
    for sec in snapshot['sections']:
        n=sec['number'];out=[f'## {n}. {TITLES[n-1]}','']
        if sec.get('applicability','applicable')!='applicable':
            out += [sec['reason'],'']
            if n==4 and sec.get('applicability')=='unverified':
                for row in sec.get('pending_source',[]):
                    label='**【'+row['status']+'】【'+row['id']+'】【'+row['title']+'】**'
                    out += [field_line(label,row['prose']),'']
            chunks.append('\n'.join(out));continue
        if n in [4,6]:
            states=STATES[n];rows=sec['records'];name='执行总览' if n==4 else '验收总览'
            values=[f'{PREFIX[n]} 总数：{len(rows)}']+[f'{s}：{sum(r["status"]==s for r in rows)}' for s in states]
            out += [f'**{name}**：'+'；'.join(values),'']
        if n==5:
            fs={f['path']:f['change'] for r in sec['records'] for f in r['fields']['修改对象']}
            out += ['**修改总览**：'+f'MOD 总数：{len(sec["records"])}；变更文件总数：{len(fs)}'+''.join(f'；{k}：{list(fs.values()).count(k)}' for k in FILE_TYPES),'']
        if n in FIELDS:
            for rec in sec['records']:
                tag=(f'【{rec["status"]}】' if n in STATES else '')+f'【{rec["id"]}】【{rec["title"]}】'
                out += ['**'+tag+'：**','']
                for label in FIELDS[n]:
                    if label not in rec['fields']:continue
                    value=rec['fields'][label]
                    if isinstance(value,str):
                        extra=rec.get('explanations',{}).get(label,'')
                        if extra:value=value.rstrip('；。')+'；'+extra
                        if label=='关联记录' and rec.get('record_refs') is not None:value='、'.join(rec['record_refs'])
                        out += [field_line(label,value),''];continue
                    out += ['- '+label+'：']
                    for i,item in enumerate(value):
                        if label=='操作步骤':lead=f'  {i+1}. '
                        else:lead='  - '
                        if label=='修改对象':
                            detail=f'【{item["change"]}】`{item["path"]}`'
                            if item.get('previous_path'):detail=f'【{item["change"]}】`{item["previous_path"]}` → `{item["path"]}`'
                            detail+='：'+item['text']
                        elif label=='证据来源':
                            e=snapshot['evidence'][item['evidence_id']];detail=f'`{e["locator"]}`：'+item['text']
                        else:detail=(item.get('label','')+'：' if item.get('label') else '')+item.get('text','')
                        out.append(lead+detail.replace('\n','\n    '))
                    out.append('')
        elif n==3:
            for term in sec.get('terms',[]):
                label=(term.get('abbreviation','')+' ' if term.get('abbreviation') else '')+term['chinese']
                # A verified local meaning is not an official acronym expansion.
                # Keep its English metadata intact without mislabelling the title.
                if term.get('kind')!='local_alias':label+='（'+term['english']+'）'
                out += [field_line('**'+label+'**',term['description']),'']
        elif n in [2,10]:
            for i,sub in enumerate(sec.get('subsections',[])):
                out += [f'### {n}.{i+1}. {sub["title"]}','']
                for paragraph in sub['paragraphs']:out += [paragraph,'']
        elif n==11:
            for item in sec.get('keypoints',[]):out += ['**'+item['title']+'**','',field_line('关键事实',item['fact']),'',field_line('实际含义',item['meaning']),'']
        elif n==1:
            for group in sec.get('groups',[]):
                out += ['**'+group['title']+'**：','']
                for item in group['fields']:out += [field_line(item['label'],item['text']),'']
        chunks.append('\n'.join(out).rstrip())
    return '\n\n'.join(chunks).rstrip()+'\n'


def chat_digest(snapshot:dict,report_locator:str|None,quality:str,limit:int=900)->str:
    """Short factual projection. Never dump the full report on unavailable AEMP."""
    ident=snapshot['identity'];r=snapshot['revision']
    source=snapshot.get('chat',{})
    texts=[]
    for key in ['result','changes','limits','next_action']:
        value=source.get(key,'')
        if value:texts.append(value)
    # Chat prose must be supplied from the same immutable report snapshot and reviewed.
    header=f'{ident["turn_id"]} · 报告修订 {r}'
    if not texts:texts=['本轮执行记录已整理，具体成果与仍需确认的事项见完整报告']
    text=header+'\n\n'+'\n\n'.join(texts)
    suffix='\n\n完整报告：'+(report_locator or '当前项目的 CURRENT.md；观察站尚未确认接收本次修订')
    # Quality review state is available in the report observer metadata, not a
    # repetitive instructional disclaimer appended to every chat message.
    if len(text)+len(suffix)>limit:
        # Oversize is a repair target, never permission to erase an action/limit.
        raise ContractError('CHAT_REQUIRES_BOUNDED_REPAIR')
    return text+suffix+'\n'


def markdown_headings(text:str)->list[tuple[int,str]]:
    found=[];fence=None
    for line in text.replace('\r\n','\n').splitlines():
        m=re.match(r'^\s*(`{3,}|~{3,})',line)
        if m:
            if fence is None:fence=m.group(1)[0]
            elif m.group(1)[0]==fence:fence=None
            continue
        if fence:continue
        m=re.match(r'^## (\d+)\. (.+)$',line)
        if m:found.append((int(m.group(1)),m.group(2)))
    return found


def verify_artifact(markdown:str,snapshot:dict)->bool:
    """Compare the ACTUAL extracted report body after native save/host capture."""
    if markdown.replace('\r\n','\n')!=render(snapshot):
        raise ContractError('ACTUAL_ARTIFACT_DIFFERS_FROM_VALIDATED_RENDER')
    return True
