# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import hashlib,re
from pathlib import Path
from .contract import digest


def compile_reference(path:Path)->dict:
    """Index approved text without mutating bytes or treating independent case IDs as facts."""
    raw=path.read_bytes();text=raw.decode('utf-8-sig').replace('\r\n','\n')
    section=0;mode='guidance';rows=[];cases={}
    for no,line in enumerate(text.splitlines(),1):
        m=re.match(r'^(?:\*\*)?## (\d+)\.\s',line)
        if m:section=int(m.group(1));mode='guidance'
        if '### 填写案例' in line:mode='example'
        if mode=='example':cases.setdefault(str(section),[]).append({'line':no,'text':line})
        for i,m in enumerate(re.finditer(r'<约束[：:]([^>]*)>',line)):
            label=re.sub(r'^[\\\-*\s]+','',line.split('<约束',1)[0]).strip('：: *')
            row={'id':f'R{section:02d}-{no:04d}-{i}','section':section,'field':label,'line':no,'text':m.group(1),
                 'executor':'unassigned','verification':'not_evaluated'}
            rows.append(row)
    return {'reference_sha256':hashlib.sha256(raw).hexdigest(),'rules':rows,'examples':cases,'index_digest':digest(rows)}


def local_context(index:dict,section:int,field:str,facts:dict)->dict:
    selected=[r for r in index['rules'] if r['section']==section and (r['field']==field or not r['field'])]
    # Keep one compact, same-field exemplar. Do not repeat every case/whole ledger.
    examples=[]
    for row in index['examples'].get(str(section),[]):
        if re.match(r'^- '+re.escape(field)+r'[：:]',row['text']):examples.append(row);break
    return {'rules':selected,'examples':examples,'facts':facts,'reference_sha256':index['reference_sha256']}
