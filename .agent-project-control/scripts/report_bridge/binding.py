# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import copy
from .contract import canonical,digest,ContractError

def machine_projection(report:dict)->dict:
    out={k:copy.deepcopy(report.get(k)) for k in ['schema','identity','revision','facts','evidence','change_manifest','native_sources','verified_term_registry']}
    out['sections']=[]
    for sec in report['sections']:
        row={k:copy.deepcopy(sec.get(k)) for k in ['number','source_items','applicability','pending_source','summaries']}
        if sec['number']==1:row['groups']=copy.deepcopy(sec.get('groups'))
        if sec['number']==3:row['term_definitions']=[{k:v for k,v in t.items() if k!='description'} for t in sec.get('terms',[])]
        row['records']=[]
        for record in sec.get('records',[]):
            r={k:copy.deepcopy(record.get(k)) for k in ['id','title','status','fact_refs','evidence_refs','record_refs','required_tests','locked','short_field_basis']}
            r['source_fields']={k:copy.deepcopy(record.get('fields',{}).get(k)) for k in record.get('locked',{}) if k!='status'}
            r['list_structure']={f:[{k:v for k,v in item.items() if k!='text'} for item in value] for f,value in record.get('fields',{}).items() if isinstance(value,list)}
            r['files']=[{k:v for k,v in f.items() if k!='text'} for f in record.get('fields',{}).get('修改对象',[]) ] if isinstance(record.get('fields',{}).get('修改对象'),list) else []
            row['records'].append(r)
        out['sections'].append(row)
    return out

def assert_same_authority(report:dict,captured:dict):
    """captured is supplied by native code, never by the generating model."""
    if report.get('source_digest')!=captured.get('source_digest') or machine_projection(report)!=machine_projection(captured):
        raise ContractError('MACHINE_FACTS_CHANGED')
    return True
