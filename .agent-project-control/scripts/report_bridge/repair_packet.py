# APCF-META {"schema":1,"visibility":"public"}
"""Small, source-bound repair packets. Full ledgers remain outside model context."""
from __future__ import annotations
from copy import deepcopy
from hashlib import sha256
import json

def hash_value(x):
    from .contract import digest
    return digest(x)
def pointer_get(root,pointer):
    cur=root
    if not pointer.startswith('/'):raise ValueError('absolute_pointer_required')
    for token in pointer[1:].split('/'):
        token=token.replace('~1','/').replace('~0','~')
        cur=cur[int(token)] if isinstance(cur,list) else cur[token]
    return cur

def build_packet(snapshot, targets, diagnostics, rule_index, example_index, *, policy_capsule):
    if not targets:raise ValueError('repair_targets_required')
    excerpts=[];rules=[];anchors=[];fact_ids=set();evidence_ids=set();seen_rules=set()
    for path in targets:
        current=pointer_get(snapshot,path)
        if not isinstance(current,str):raise ValueError('only_text_may_be_repaired')
        bits=path.strip('/').split('/');section=None;record=None
        if len(bits)>=2 and bits[0]=='sections':
            section=snapshot['sections'][int(bits[1])]
            if 'records' in bits:
                at=bits.index('records');record=section['records'][int(bits[at+1])]
        field=bits[-1].replace('~1','/').replace('~0','~')
        row={'pointer':path,'before':current,'before_digest':hash_value(current),'field':field,'section':section.get('number') if section else None}
        if record:
            if 'fields' in bits and field in record.get('locked',{}):
                raise ValueError('immutable_source_field')
            row['intent']={'id':record.get('id'),'title':record.get('title'),'status':record.get('status'),'original_requirements':deepcopy(record.get('locked',{}))}
            row['related_fields']={k:v for k,v in record.get('fields',{}).items() if isinstance(v,str) and k in ('任务缘由','行动要求','验收标准','预期结果','执行结果','实际结果')}
            fact_ids.update(record.get('fact_refs',[]));evidence_ids.update(record.get('evidence_refs',[]))
        elif bits[0]=='chat':
            # Summary repairs need the other protected message duties, rather than
            # an entire ledger. Their text cannot disappear to satisfy a limit.
            row['related_fields']=deepcopy(snapshot.get('chat',{}))
            row['delivery_limit']='900 characters including identity and the actual report link; preserve every necessary action and material limitation'
        excerpts.append(row)
        for r in rule_index.get('rules',[]):
            if r.get('section')==row['section'] and (r.get('field') in (None,field)) and r.get('rule_id') not in seen_rules:
                seen_rules.add(r['rule_id']);rules.append({k:r[k] for k in ('rule_id','constraint','source_sha256','line') if k in r})
        matching=[x for x in example_index.get('examples',[]) if x.get('section')==row['section'] and x.get('text','').lstrip().startswith('- '+field+'：')]
        if matching:anchors.append({'pointer':path,'example':matching[0]['text'],'role':'style_only_not_execution_fact'})
    return {'schema':'apcf.local-repair/1','identity':deepcopy(snapshot['identity']),'revision':snapshot['revision'],'source_digest':snapshot['source_digest'],
            'base_digest':hash_value(snapshot),'targets':excerpts,'diagnostics':diagnostics,
            'facts':{k:deepcopy(snapshot.get('facts',{})[k]) for k in fact_ids if k in snapshot.get('facts',{})},
            'evidence':{k:deepcopy(snapshot.get('evidence',{})[k]) for k in evidence_ids if k in snapshot.get('evidence',{})},
            'rules':rules,'anchors':anchors,'policy_capsule':deepcopy(policy_capsule),
            'constraints':['Return only authorized text replacements.','Never modify facts, IDs, status, ordering, counts or original criteria.','Do not copy teaching-example facts.','Missing evidence is not a request to invent an observation.']}
