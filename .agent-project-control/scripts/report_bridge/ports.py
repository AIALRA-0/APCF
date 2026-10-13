# APCF-META {"schema":1,"visibility":"public"}
"""Actual APCF delivery, short-message prepare/observe and observation outbox ports."""
from __future__ import annotations
import copy
import hashlib
import json
import re
from pathlib import Path
from .contract import digest, text_digest, ContractError, Issue
from .native import capture, NativeReportWriter, sources_unchanged
from .render import render, chat_digest, verify_artifact
from .binding import assert_same_authority
from .repair import repair, model_command
from .repair_packet import build_packet
from .quality import review_request, accept_review
from .guidance import compile_reference
from .storage import envelope, enqueue
from .publication import PreparedPublication
from report14.bindings import report_text, safe_turn
from repair_io import inside, atomic, private_json


def draft_from_markdown(text):
    """Input compatibility only; native capture still controls all source facts."""
    from report14.markdown import parse, records, fields, inline, body
    from .contract import TITLES,FIELDS
    doc=parse(report_text(text))
    if [s.number for s in doc.sections]!=list(range(1,15)):return None
    draft={'schema':'apcf.report-observation/1','sections':[],'chat':{}}
    for sec in doc.sections:
        n=sec.number;row={'number':n,'title':TITLES[n-1]}
        content=body(doc,sec).strip()
        if not content or content.startswith(('本轮无相关事项','本轮不适用','当前尚无足够记录')):
            row.update(applicability='none',reason=content or '本轮无相关事项')
        elif n in FIELDS:
            rows,_=records(sec);rs=[]
            for rec in rows:
                parts=rec['parts']
                if len(parts)<2:continue
                rid=parts[-2];fs={f['name']:f['value'] for f in rec['fields'] if f['name'] in FIELDS[n]}
                # Native adapter owns nested MOD/EV paths; prose-only sections need
                # typed input for nested commands. Never guess a executable step.
                if any(f['lists'] for f in rec['fields']):continue
                r={'id':rid,'title':parts[-1],'fields':fs,'record_refs':re.findall(r'(?:CL|MOD|TEST|EV)-\d{2,}',fs.get('关联记录',''))}
                if n in (4,6):r['status']=parts[0]
                rs.append(r)
            row.update(records=rs,source_items=[r['id'] for r in rs])
        elif n==3:
            terms=[]
            for line in content.splitlines():
                m=re.match(r'^- (.*?)（([^（）]+)）：(.+)$',line.replace('**',''))
                if not m:continue
                name=m[1];abbr='';zh=name
                if ' ' in name and re.fullmatch(r'[A-Z][A-Z0-9_.-]+',name.split(' ',1)[0]):abbr,zh=name.split(' ',1)
                terms.append({'abbreviation':abbr,'chinese':zh,'english':m[2],'description':m[3],'kind':'abbreviation' if abbr else 'term'})
            row['terms']=terms
        elif n in (2,10):
            subs=[]
            for node in sec.nodes:
                if node.type=='heading':
                    title=re.sub(r'^\d+\.\d+\. ','',inline(node));subs.append({'title':title,'paragraphs':[]})
                elif node.type=='paragraph' and subs:subs[-1]['paragraphs'].append(inline(node))
            row['subsections']=subs
        elif n==11:
            kp=[]
            for node in sec.nodes:
                text=inline(node)
                if node.type=='paragraph' and text.startswith('**') and text.endswith('**'):kp.append({'title':text.strip('*'),'fact':'','meaning':''})
                elif node.type=='bullet_list' and kp:
                    for f in fields([node]):
                        if f['name']=='关键事实':kp[-1]['fact']=f['value']
                        if f['name']=='实际含义':kp[-1]['meaning']=f['value']
            row['keypoints']=kp
        draft['sections'].append(row)
    return draft


def narrative_pointers(snapshot):
    out=[]
    for i,sec in enumerate(snapshot['sections']):
        for j,rec in enumerate(sec.get('records',[])):
            for name,value in rec.get('fields',{}).items():
                if isinstance(value,str) and value.strip():out.append(f'/sections/{i}/records/{j}/fields/{name}')
            for name,value in rec.get('explanations',{}).items():
                if isinstance(value,str) and value.strip():out.append(f'/sections/{i}/records/{j}/explanations/{name}')
        for j,sub in enumerate(sec.get('subsections',[])):
            out += [f'/sections/{i}/subsections/{j}/paragraphs/{k}' for k in range(len(sub.get('paragraphs',[])))]
        out += [f'/sections/{i}/terms/{j}/description' for j in range(len(sec.get('terms',[])))]
        for j,term in enumerate(sec.get('terms',[])):
            out += [f'/sections/{i}/terms/{j}/{key}' for key in ('chinese','english')]
        for j,item in enumerate(sec.get('keypoints',[])):
            out += [f'/sections/{i}/keypoints/{j}/{key}' for key in ('title','fact','meaning')]
        for j,group in enumerate(sec.get('groups',[])):
            out += [f'/sections/{i}/groups/{j}/fields/{k}/text' for k in range(len(group.get('fields',[])))]
        if sec.get('reason'):out.append(f'/sections/{i}/reason')
        out += [f'/sections/{i}/pending_source/{j}/prose' for j in range(len(sec.get('pending_source',[])))]
        for j,rec in enumerate(sec.get('records',[])):
            for name,value in rec.get('fields',{}).items():
                if isinstance(value,list):out += [f'/sections/{i}/records/{j}/fields/{name}/{k}/text' for k,v in enumerate(value) if v.get('text')]
    out += ['/chat/'+k for k,v in snapshot.get('chat',{}).items() if isinstance(v,str) and v]
    return out


def reference_index(root):
    index=compile_reference(Path(root)/'.agent-project-control/reporting/APPROVED-REFERENCE.md')
    for row in index['rules']:
        field=row.get('field','');constraint=row['text']
        row.update(rule_id=row['id'],constraint=constraint,source_sha256=index['reference_sha256'])
        if any(x in constraint for x in ('实际发送','实际保存','原生','下载','真实宿主','事务')):executor='engineering'
        elif any(x in constraint for x in ('总数','统计','摘要','顺序','编号唯一','身份')):executor='factual'
        elif any(x in constraint for x in ('层级','一级','二级','固定','格式','空行','缩进','字段顺序')):executor='renderer'
        else:executor='content'
        row['executor']=executor;row['verification']='not_evaluated'
    index['example_rows']=[{'section':int(n),**r} for n,rows in index['examples'].items() for r in rows]
    index['index_digest']=digest(index['rules'])
    return index


def agent_config(root):
    # Configuration is a maintainer-owned local file, never a field in a model draft.
    p=Path(root)/'.agent-project-control/runtime/tmp/report14/quality-agent.json'
    if not p.is_file():return None
    row=json.loads(p.read_text('utf-8-sig'))
    if row.get('enabled') is not True:return None
    command=row.get('command')
    if not isinstance(command,list) or not command or not all(isinstance(x,str) for x in command):raise ContractError('MODEL_CONFIG_INVALID')
    reviewer=row.get('reviewer_command',command)
    if not isinstance(reviewer,list) or not reviewer or not all(isinstance(x,str) for x in reviewer):raise ContractError('REVIEW_CONFIG_INVALID')
    return {'writer':command,'reviewer':reviewer}


def observe_saved(root,outbox,store):
    """Optional read-model delivery; a failed observer never invalidates native save."""
    p=Path(root)/'.agent-project-control/runtime/tmp/report14/quality-observer.json'
    if not p.is_file():return {'status':'disabled','confirmed':False}
    try:
        cfg=json.loads(p.read_text('utf-8-sig'))
        if cfg.get('enabled') is not True:return {'status':'disabled','confirmed':False}
        from .transport import send_once
        ack=send_once(outbox,cfg['endpoint'],cfg.get('token_env','APCF_OBSERVER_TOKEN'),enabled=True,
            query_endpoint=cfg.get('query_endpoint'),binding_file=cfg['binding_file'],
            native_contracts_module=cfg.get('native_contracts_module'),timeout=cfg.get('timeout',20))
        return {'status':'confirmed','confirmed':True,'ack':ack}
    except Exception as exc:
        store.audit({'phase':'observer_unconfirmed','error_type':type(exc).__name__})
        return {'status':'unconfirmed','confirmed':False}


def _reviewer(command,index,store):
    def review(snapshot,remaining):
        pointers=narrative_pointers(snapshot)
        request=review_request(snapshot,index['rules'],[r for r in index['example_rows'] if r['text'].lstrip().startswith('- ')][:30])
        request['rendered_report']=render(snapshot)
        request['required_pointers']=pointers
        # Read only byte-bound native materials; excerpts are explicitly partial.
        # A path and hash alone cannot support a semantic claim about its contents.
        import hashlib
        materials=[]
        for rel,expected in snapshot.get('native_sources',{}).items():
            if expected is None:continue
            path=inside(store.root,rel,must_exist=True);data=path.read_bytes()
            if hashlib.sha256(data).hexdigest()!=expected:raise ContractError('REVIEW_SOURCE_CHANGED')
            try:text=data.decode('utf-8-sig')
            except UnicodeError:continue
            parts=[{'start':0,'text':text[:6000]}]
            if len(text)>6000:parts.append({'start':max(6000,len(text)-6000),'text':text[max(6000,len(text)-6000):]})
            materials.append({'path':rel,'sha256':expected,'characters':len(text),'complete':len(text)<=12000,'excerpts':parts})
        request['verified_materials']=materials
        request['review_stage']='Candidate intended for native save; saved claims and entry ownership must separately pass actual transaction/readback before any host send'
        request['protected_source_prose']=('Original goal promises, ITERATION Objective, user REQUEST and TEST criteria are immutable source text; evaluate separate explanations without demanding that these be rewritten. '
            'Header Objective and user requirement quote those original sources. Evaluate displayed record fields together with their explanations and rendered_report; a frozen test action describes the agreed method, while its native status and actual result determine whether it ran. '
            'Pending-source rows preserve nonfinal states; do not force them into FAIL or erase already completed rows. These protections do not excuse missing factual support or inadequate authored explanations.')
        answer=model_command(command,request,min(155,remaining))
        accepted,reason=accept_review(answer,request,pointers)
        store.audit({'phase':'independent_content_review','request':request,'response':answer,'accepted':accepted,'reason':reason})
        if accepted:return []
        issues=[Issue('SEMANTIC_CONTENT',x['pointer'],x.get('reason','内容职责仍需修订'),'review') for x in answer.get('issues',[]) if isinstance(x,dict) and isinstance(x.get('pointer'),str)]
        return issues or [Issue('REVIEW_INCOMPLETE','/','内容复核未完整覆盖当前正文','review')]
    return review


def publish(root,turn,draft=None,*,request_id='',budget_seconds=90,agent=None,reviewer=None):
    root=Path(root).resolve();turn=safe_turn(root,turn);store=__import__('report14.storage',fromlist=['Store']).Store(root)
    store.recover()
    receipt_path=turn/'evidence/report-quality-publication.json'
    previous=json.loads(receipt_path.read_text('utf-8-sig')) if receipt_path.is_file() else None
    revision=(previous['revision']+1) if previous else 1
    if isinstance(draft,str):draft=draft_from_markdown(draft)
    if draft is not None and (not isinstance(draft,dict) or draft.get('schema')!='apcf.report-observation/1'):
        raise ContractError('CURRENT_WRITE_REQUIRES_TYPED_SOURCE')
    captured=capture(root,turn,request_id,revision,draft)
    if not captured.get('chat'):
        cls=captured['sections'][3];pending=cls.get('pending_source',[]);rows=cls.get('records',[])
        complete=sum(r.get('status')=='已完成' for r in rows)
        captured['chat']={'result':f'本轮已登记 {len(rows) if not pending else len(pending)} 项目标；'+(f'已完成 {complete} 项' if not pending else '工作仍在推进，完成范围以原生清单为准'),
            'limits':'报告保存与业务完成分别核对；未完成和未验证事项以本轮清单与验收记录为准','next_action':'','changes':''}
    writer=NativeReportWriter(root,turn,request_id,captured);index=reference_index(root)
    config=agent_config(root);command=config['writer'] if config else None
    if agent is None and command:agent=lambda req,budget:model_command(command,req,min(90,budget))
    if reviewer is None and config:reviewer=_reviewer(config['reviewer'],index,store)
    def resolver(pointer,current):
        packet=build_packet(current,[pointer],[],index,{'examples':index['example_rows']},policy_capsule={
            'writing':'Use the current Writing v0.1 and Style v0.1 role requirements; no invented observations.',
            'short_fields':'Identifiers, time, references and source-backed no-special-risk fields remain short.',
            'ownership':'Original promises, evidence, results and authority are immutable.'})
        return packet
    locator=f'[当前完整报告](<{(root/"CURRENT.md").as_posix()}>)'
    def projection_check(current):
        try:chat_digest(current,locator,'needs_review')
        except ContractError as exc:
            if str(exc)!='CHAT_REQUIRES_BOUNDED_REPAIR':raise
            # Every supplied action and limitation remains in the snapshot. Repair
            # the longest prose first; never shorten by silently dropping a key.
            values=current.get('chat',{})
            key=max((k for k in ('result','changes','limits','next_action') if values.get(k)),key=lambda k:len(values[k]),default=None)
            return [Issue('QUALITY_CHAT_TOO_LONG','/chat/'+key,'当前实际聊天正文超过900字上限；压缩重复说明并保留全部关键结果、限制及唯一必要行动','review')] if key else []
        return []
    result=repair(captured,agent,resolver,semantic_reviewer=reviewer,projection_checker=projection_check,deadline_seconds=max(1,min(180,budget_seconds)))
    store.audit({'phase':'quality_pipeline','source_digest':captured['source_digest'],**{k:v for k,v in result.items() if k!='report'}})
    snapshot=result['report'];assert_same_authority(snapshot,captured)
    if result['structure']!='valid':raise ContractError('TYPED_STRUCTURE_INVALID')
    markdown=render(snapshot)
    summary=chat_digest(snapshot,locator,result['quality'])
    publication=PreparedPublication.prepare(project_id=snapshot['identity']['project_id'],turn_id=snapshot['identity']['turn_id'],revision=revision,
        source_digest=snapshot['source_digest'],full_report=markdown,short_chat=summary)
    saved=writer.save_report(markdown=markdown,snapshot=snapshot,expected_source_digest=captured['source_digest'],report_digest=digest(snapshot),quality=result['quality'])
    verify_artifact(writer.read_saved_report(saved),snapshot)
    publication.verify_saved(current_report=writer.read_saved_report(saved),turn_report=report_text((turn/'TURN.md').read_text('utf-8-sig')))
    observation={'status':'enqueue_pending','confirmed':False}
    try:
        outbox=enqueue(writer.home,envelope(snapshot,result['quality']))
        observation=observe_saved(root,outbox,store)
        if observation['confirmed']:
            summary=chat_digest(snapshot,'[AEMP完整报告]('+observation['ack']['locator']+')',result['quality'])
            publication=PreparedPublication.prepare(project_id=snapshot['identity']['project_id'],turn_id=snapshot['identity']['turn_id'],revision=revision,
                source_digest=snapshot['source_digest'],full_report=markdown,short_chat=summary)
            publication.verify_saved(current_report=writer.read_saved_report(saved),turn_report=report_text((turn/'TURN.md').read_text('utf-8-sig')))
    except Exception as exc:store.audit({'phase':'observer_enqueue_pending','error_type':type(exc).__name__})
    chat_path=turn/'evidence'/('CHAT-r'+str(revision)+'.md')
    atomic(chat_path,summary.encode('utf-8'),expected=None,compare=True)
    # Keep the exact transport bytes; visibility belongs in adjacent metadata.
    chat_meta=('# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\nsha256: '
               +hashlib.sha256(chat_path.read_bytes()).hexdigest()+'\n').encode('utf-8')
    atomic(chat_path.with_name(chat_path.name+'.apcf-meta.yaml'),chat_meta,expected=None,compare=True)
    row={**saved,'chat_sha256':text_digest(summary),'chat_path':chat_path.relative_to(root).as_posix(),
        'report_sha256':text_digest(markdown.strip()),
        'surface':'chat_summary','observation':observation,'host_scope':'cooperative; actual host capture is separately required'}
    private_json(turn/'evidence/report-quality-delivery.json',row)
    return {'report':markdown,'chat':summary,'snapshot':snapshot,'receipt':row,'quality':result['quality'],'repair':result}


def prepared(root,turn,request_id):
    import execution_session
    root=Path(root).resolve();turn=safe_turn(root,turn);execution_session.load(turn,request_id)
    p=turn/'evidence/report-quality-delivery.json'
    if not p.is_file():return publish(root,turn,request_id=request_id)
    row=json.loads(p.read_text('utf-8-sig'))
    if row['request_id']!=request_id:raise ContractError('STALE_REQUEST')
    archive=inside(root,row['snapshot_path'],must_exist=True)
    saved=json.loads(archive.read_text('utf-8-sig'));snapshot=saved['snapshot']
    writer=NativeReportWriter(root,turn,request_id,snapshot);report=writer.read_saved_report(row)
    if not sources_unchanged(root,snapshot['native_sources']):raise ContractError('STALE_PREPARED_SOURCE')
    chat=inside(root,row['chat_path'],must_exist=True).read_text('utf-8')
    if text_digest(chat)!=row['chat_sha256'] or digest(snapshot)!=row['report_digest']:raise ContractError('PREPARED_BYTES_CHANGED')
    return {'report':report,'chat':chat,'snapshot':snapshot,'receipt':row,'quality':row['quality']}


def emit(root,turn,request_id,output,*,observed=False):
    root=Path(root).resolve();turn=safe_turn(root,turn);value=prepared(root,turn,request_id)
    output=Path(output).absolute()
    from repair_io import linked
    if any(linked(p) for p in (output,*output.parents)):raise ContractError('UNSAFE_CHAT_PATH')
    if output.resolve().is_relative_to(root/'.agent-project-control') and not output.resolve().is_relative_to(turn/'evidence'):raise ContractError('USE_MANAGED_STATE_WRITER')
    text=value['chat'];row=value['receipt']
    publication=PreparedPublication.prepare(project_id=row['identity']['project_id'],turn_id=row['identity']['turn_id'],revision=row['revision'],source_digest=row['source_digest'],full_report=value['report'],short_chat=text)
    if observed:
        captured_binding=json.loads(output.with_name(output.name+'.binding.json').read_text('utf-8-sig'))
        if captured_binding.get('stage')!='captured' or not captured_binding.get('host_event_id'):raise ContractError('ACTUAL_HOST_BINDING_REQUIRED')
        for key in ('request_id','identity','report_digest'):
            if captured_binding.get(key)!=row[key]:raise ContractError('CAPTURE_IDENTITY_CHANGED')
        publication.verify_sent(captured_chat=output.read_text('utf-8'),actual_revision=captured_binding.get('revision'),actual_source_digest=captured_binding.get('source_digest'))
        status='OBSERVED_SUMMARY_MATCH'
    else:
        data=text.encode('utf-8');before=output.read_bytes() if output.is_file() else None
        if before is not None and before!=data:raise ContractError('CHAT_OUTPUT_COLLISION')
        if before is None:atomic(output,data,expected=None,compare=True)
        binding={k:row[k] for k in ('request_id','identity','revision','source_digest','report_digest','chat_sha256')}
        binding.update(stage='prepared',surface='chat_summary')
        binding_path=output.with_name(output.name+'.binding.json')
        if binding_path.is_file() and json.loads(binding_path.read_text('utf-8-sig'))!=binding:raise ContractError('CHAT_BINDING_COLLISION')
        if not binding_path.exists():private_json(binding_path,binding,create=True)
        status='PREPARED_SUMMARY_FOR_DELIVERY'
    result={**row,'status':status,'output_sha256':text_digest(text),'current_saved':True,'business_finalized':False}
    private_json(turn/'evidence/delivery-text.json',result)
    return result
