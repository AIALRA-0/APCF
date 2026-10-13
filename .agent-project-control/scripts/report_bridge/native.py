# APCF-META {"schema":1,"visibility":"public"}
"""Trusted native ledger projection and the existing TURN/CURRENT transaction.

The model supplies prose, never source hashes, completion states or file counts.
Report checkpoints do not change execution status or business Finalize receipts.
"""
from __future__ import annotations
import copy
import json
import re
from pathlib import Path
from .contract import VERSION, TITLES, FIELDS, digest, text_digest, validate, ContractError
from .binding import assert_same_authority
from .render import render, verify_artifact
from report14.bindings import safe_turn, report_text, published_meta
from report14.storage import Store
from repair_io import inside, private_json


def _field(row, key, default=''):
    value=row.get(key)
    if isinstance(value,str):return value
    pair=row.get('_spans',{}).get(key)
    prose=row.get('_prose',row.get('body',''))
    return prose[pair[0]:pair[1]] if isinstance(pair,list) and len(pair)==2 else default


def _read(root, rel, hashes):
    path=inside(root,rel,must_exist=True)
    data=path.read_bytes();hashes[rel]=__import__('hashlib').sha256(data).hexdigest()
    return data.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n')


def _manifest(root,turn,hashes):
    """Compare declared paths with their earliest sealed native preimages."""
    preimages={};order=[]
    for path in sorted((turn/'evidence').glob('plan-revision-*.json')):
        row=json.loads(_read(root,path.relative_to(root).as_posix(),hashes))
        for item in row.get('target_preimages',[]):
            rel=item['path']
            if rel not in preimages:preimages[rel]=item;order.append(rel)
    baseline=turn/'evidence/activity-baseline.json'
    if baseline.is_file():
        row=json.loads(_read(root,baseline.relative_to(root).as_posix(),hashes))
        if row.get('turn')!=turn.relative_to(root).as_posix():raise ContractError('FOREIGN_ACTIVITY_BASELINE')
        # The lifecycle captured existing dirty bytes before investigation. A
        # target first declared by a later plan must not hide earlier changes by
        # treating a post-investigation byte image as its turn-start preimage.
        for item in row.get('dirty_rows',[]):
            if item.get('path') in preimages:preimages[item['path']]=item
    excluded={turn.relative_to(root).as_posix()+'/TURN.md','CURRENT.md'}
    result=[]
    for rel in order:
        if rel in excluded or '/evidence/' in rel or '/runtime/' in rel:continue
        path=inside(root,rel);old=preimages[rel]
        if path.is_dir():continue
        before=old.get('sha256') if old.get('state')=='file' else None
        after=__import__('hashlib').sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        if before==after:continue
        change='新增' if before is None else '删除' if after is None else '修改'
        result.append({'path':rel,'change':change,'before_sha256':before,'after_sha256':after})
        hashes[rel]=after
    return result


def capture(root,turn,request_id,revision=1,draft=None):
    """Capture actual native sources; authored explanations are separate from facts."""
    from test_ledger import parse_checklist,parse_tests,validate_file
    import execution_session
    root=Path(root).resolve();turn=safe_turn(root,turn)
    execution_session.load(turn,request_id)
    errors=validate_file(turn/'TEST.md',turn/'CHECKLIST.md')
    if errors:raise ContractError('NATIVE_LEDGER_INVALID')
    hashes={};rel=turn.relative_to(root).as_posix()
    texts={name:_read(root,rel+'/'+name,hashes) for name in ('REQUEST.md','CHECKLIST.md','TEST.md')}
    cls=parse_checklist(texts['CHECKLIST.md']);tests=parse_tests(texts['TEST.md'])
    manifest=_manifest(root,turn,hashes)
    identity={'project_id':root.name,'producer_id':'apcf-template','iteration_id':turn.parents[1].name.split('_')[0],'turn_id':turn.name.split('_')[0]}
    s={'schema':VERSION,'identity':identity,'revision':revision,'source_digest':'0'*64,
       'facts':{},'evidence':{},'change_manifest':[{'path':x['path'],'change':x['change']} for x in manifest],
       'sections':[{'number':i,'title':title,'applicability':'none','reason':'本轮无相关事项：当前原生记录没有登记这类事项'} for i,title in enumerate(TITLES,1)],'chat':{}}
    if draft:
        for n in (2,3,8,9,10,11,12,13,14):s['sections'][n-1]=copy.deepcopy(draft['sections'][n-1])
        s['chat']=copy.deepcopy(draft.get('chat',{}))
    session=json.loads((turn/'evidence/execution-session.json').read_text('utf-8-sig'))
    s['facts']['native-session']={'value':{'created_at':session['created_at']},'source_ref':rel+'/evidence/execution-session.json#created_at'}
    def group(title,values):return {'title':title,'fields':[{'label':k,'text':v} for k,v in values.items()]}
    completed=[r['id'] for r in cls if r['status']=='已完成'];unfinished=[r['id'] for r in cls if r['status']!='已完成']
    header={'number':1,'groups':[
        group('当前 IT',{'IT 编号及标题':identity['iteration_id']+'；'+turn.parents[1].name.split('_',2)[-1],
            '长期工作目标':'以本轮原始请求和事前清单约定为准','当前进度':'已登记 '+str(len(cls))+' 项目标，已完成 '+str(len(completed))+' 项；已完成范围：'+('、'.join(r['object'] for r in cls if r['status']=='已完成') or '尚无')+'；仍在推进：'+('、'.join(r['object'] for r in cls if r['status']!='已完成') or '无'),'动态扩展':''}),
        group('当前 TR',{'TR 编号及标题':identity['turn_id']+'；'+turn.name.split('_',2)[-1],'所属 IT':identity['iteration_id'],
            '用户具体要求':'本轮希望取得可验收结果：'+ '；'.join(r['object']+'须满足'+_field(r,'criterion') for r in cls),
            '本轮处理范围':'当前目标涉及'+ '、'.join(r['object'] for r in cls)+'；具体源码边界以本轮封存文件计划为准','动态扩展':''}),
        group('时间',{'记录事件':'本轮执行请求建立','发生时间':session['created_at'],'核对来源':'当前请求的原生执行会话记录','动态扩展':''}),
        group('执行清单',{'清单来源':'当前 TR 的 `CHECKLIST.md`','清单总数':str(len(cls)),
            '执行统计':'；'.join(k+'：'+str(sum(r['status']==k for r in cls)) for k in dict.fromkeys(r['status'] for r in cls)),
            '关键情况':'仍待完成：'+('、'.join(unfinished) or '当前清单没有未完成项目'),'动态扩展':''}),
        group('验收摘要',{'验收来源':'当前 TR 的 `TEST.md`','验收范围':'原生验收记录的完整有序集合',
            '状态统计':'；'.join(k+'：'+str(sum(r['status']==k for r in tests)) for k in dict.fromkeys(r['status'] for r in tests)),
            '总体判断':'按每项实际结果和原始证据判断，不由报告保存推导业务完成','动态扩展':''}),
        group('结果状态',{'本轮目标':'完成当前请求的事前约定','已完成事项':'、'.join(completed) or '当前清单尚无已完成项目',
            '未完成事项':'、'.join(unfinished) or '当前清单没有未完成项目',
            '整体状态':'全部清单已完成；业务正式归档仍以原生 Finalize 结果为准' if not unfinished else '本轮仍在推进，未完成项目保持真实状态','动态扩展':''})]}
    # The approved contract owns every status group and its field order.
    # Native prose must bind local facts without guessing a production release.
    header_spec=json.loads(_read(root,'.agent-project-control/reporting/contract.json',hashes))['sections'][0]
    if header_spec['number']!=1 or header_spec['kind']!='header':raise ContractError('NATIVE_HEADER_CONTRACT_INVALID')
    iteration_text=_read(root,(turn.parents[1]/'ITERATION.md').relative_to(root).as_posix(),hashes)
    objective=re.search(r'^## [^\n]*(?:Objective|目标)[^\n]*\n(.*?)(?=^## |\Z)',iteration_text,re.M|re.S)
    if not objective:objective=re.search(r'^- \*\*Objective\*\*：(.+)$',iteration_text,re.M)
    if objective:header['groups'][0]['fields'][1]['text']=objective.group(1).strip()
    cfg=_read(root,'.agent-project-control/framework.yaml',hashes)
    schema=re.search(r'^schema_version:\s*[\"\']?([^\"\'\s]+)',cfg,re.M)
    values={g['title']:{f['label']:f['text'] for f in g['fields']} for g in header['groups']}
    test_status={k:sum(r['status']==k for r in tests) for k in ('PASS','FAIL','BLOCKED','未执行')}
    values['验收摘要']['状态统计']='TEST 总数：'+str(len(tests))+'；'+'；'.join({'PASS':'通过','FAIL':'失败','BLOCKED':'阻塞','未执行':'未执行'}[k]+'：'+str(v) for k,v in test_status.items())
    native_limits='、'.join(r['title'] for r in s['sections'][8].get('records',[])) or ('仍有原生目标未完成' if unfinished else '本轮原生清单无未完成项，其他未验证范围以当前正文说明为准')
    proof_rows=[r for r in tests if r['status']=='PASS']
    proof_text='；'.join(r['id']+'：'+_field(r,'actual') for r in proof_rows[:2]) or '当前原生验收尚无通过记录，不能声明本轮目标已被证实'
    proof_paths='；'.join(_field(r,'evidence') for r in proof_rows[:2]) or '当前尚无已通过验收引用的关键证据'
    values.update({
        '版本':{'当前产品':root.name+' 当前本地报告实现','正式版本':'本次源捕获未核对公开发行版本，正式版本保持未知',
                '候选版本':'本轮候选为未提交的本地文件增量；结构声明版本 '+(schema.group(1) if schema else '未取得有效值')+' 仅标识框架模式，不作为产品发行号',
                '版本关系':'本地接入与公开发行是不同交付范围；本轮报告不声称新的正式版本已发布','动态扩展':''},
        '生产提交':{'运行环境':__import__('platform').system()+' 本地工作树','当前生产提交':'未在本次源捕获中取得生产运行提交，未知',
                    '本轮候选提交':'本轮尚未创建新的版本提交；当前候选按实际源文件摘要定位',
                    '本轮部署情况':'本轮报告沿用本地原生写入者；实际保存结果按正文和当前入口的一致性回读判断，公开部署以其实际记录为准','动态扩展':''},
        '入口':{'主要入口':'[当前完整报告](<'+(root/'CURRENT.md').as_posix()+'>)','所属环境':'本地报告保存目标；本修订成功保存并回读后才成为当前入口',
                '访问条件':'需要能够访问当前项目文件；远端观察入口只在匹配确认后由聊天出口提供','次要入口':'[本轮源报告](<'+(turn/'TURN.md').as_posix()+'>)','动态扩展':''},
        '文件修改':{'修改范围':str(len(manifest))+' 个唯一文件；具体对象和类型见文件修改章节',
                    '核心变化':'当前文件变更用于支撑'+ '、'.join(r['object'] for r in cls)+'；实现与真实验收结果分别在修改说明和验收正文中对照',
                    '保护情况':'批准规范、历史和无关对象的保护以原生验收及其实际对账证据为依据，不从变更清单自行扩大结论','动态扩展':''},
        '关键证据':{'主要证明内容':proof_text,'关键证据来源':proof_paths,
                    '核对情况':'这些内容来自当前验收的实际观察和原始引用；保存前核对证据字节，所支持的业务范围仍以各项原判据为准','动态扩展':''},
        '剩余限制':{'当前情况':native_limits,'产生原因':'限制来自当前解释及原生清单所登记的范围；具体已知原因与未验证条件分别在剩余限制章节说明',
                    '实际影响':'报告保存与业务完成分别验收；当前使用和结论只覆盖真实证据支持的范围',
                    '解除方向':'沿用原验收承诺取得缺失证据，再由原生业务门禁判断是否闭环','动态扩展':''},
        '补充说明':{'额外重要事实':'报告、观察与业务状态分别核对；观察投递不会自动批准、授权或完成原生执行',
                    '单独说明原因':'同源展示只能证明报告身份和内容绑定，不能替代业务执行控制权','实际影响':'报告观察不改变原生授权与验收条件，必须分别核对真实业务结果','动态扩展':''}})
    # Summarize the captured request and already permitted narrative sections.
    # Direct model-supplied header fields remain ignored; IDs, criteria, status,
    # time and counts still come from native sources and stay immutable in repair.
    request_body=texts['REQUEST.md'].split('## My request:',1)[-1].strip()
    values['当前 TR']['用户具体要求']=request_body
    values['当前 TR']['本轮处理范围']+='；只处理原生清单与封存文件计划内的对象，其他对象保持原有边界'
    cl_counts={k:sum(r['status']==k for r in cls) for k in ('已完成','失败','阻塞','进行中','未开始')}
    values['执行清单']['执行统计']='；'.join(k+'：'+str(v) for k,v in cl_counts.items())
    values['验收摘要']['验收范围']='当前原生验收覆盖：'+'、'.join(r['object'] for r in tests)+'；实际环境和各项尚未执行范围见验收记录，不把计划中的动作算作实测'
    values['验收摘要']['总体判断']='当前 '+str(test_status['PASS'])+' 项通过，'+str(test_status['FAIL'])+' 项失败，'+str(test_status['BLOCKED'])+' 项阻塞，'+str(test_status['未执行'])+' 项未执行；已通过项只支持其原始判据，报告保存不能补足其他项的缺失证据'
    values['生产提交']['本轮部署情况']='本次源捕获运行于'+__import__('platform').system()+' 本地工作树，候选在此参与检查；本修订处于保存前候选阶段，公开部署未由本次捕获核对'
    values['关键证据']['核对情况']='捕获时实际读取这些验收引用的证据字节并绑定摘要；所列观察来自原生验收记录，其业务判断仍受各项原判据及证据范围约束'
    values['结果状态']['本轮目标']=request_body
    values['结果状态']['整体状态']='任务已完成 '+str(len(completed))+'/'+str(len(cls))+'，验收通过 '+str(test_status['PASS'])+'/'+str(len(tests))+'；本次源捕获尚未形成此修订的保存或发送回执，业务收口须另行核对原生门禁与状态保存结果'
    def narrative_fields(number):
        return [r.get('fields',{}) for r in s['sections'][number-1].get('records',[])]
    results=narrative_fields(8)
    if results:values['文件修改']['核心变化']='；'.join(str(r.get('实际成果','')) for r in results if r.get('实际成果'))
    limits=narrative_fields(9)
    if limits:
        limit_records=s['sections'][8].get('records',[])
        titles=[r['title'] for r in limit_records if r.get('fields',{}).get('当前限制')]
        if titles:
            values['剩余限制']['当前情况']='仍需处理 '+str(len(titles))+' 组边界：'+'、'.join(titles)+'；逐项当前事实见第9章'
            values['剩余限制']['实际影响']='这些边界限制相应结论与使用范围；具体影响按第9章逐项说明，已验证结果保持原判据范围'
            values['剩余限制']['解除方向']='按第9章各项解除条件取得缺失证据，再执行原生业务门禁；报告保存不会自动解除限制'
        values['剩余限制']['产生原因']='当前原生验收有 '+str(test_status['BLOCKED'])+' 项阻塞、'+str(test_status['未执行'])+' 项未执行；具体原因与依据见第9章，不从状态推断未知原因'
    for g in header_spec['groups']:
        if g['title'] not in values or any(k not in values[g['title']] for k in g['fields']):raise ContractError('NATIVE_HEADER_FIELDS_UNBOUND')
    header['groups']=[group(g['title'],{k:values[g['title']][k] for k in g['fields']}) for g in header_spec['groups']]
    s['sections'][0]=header
    all_evidence={};test_refs={row['id']:row.get('refs',[]) for row in tests}
    for n,rows in ((4,cls),(6,tests)):
        records=[];pending=[]
        for row in rows:
            rid=row['id'];fid='native-'+rid
            s['facts'][fid]={'value':{k:v for k,v in row.items() if not k.startswith('_')},'source_ref':rel+('/CHECKLIST.md' if n==4 else '/TEST.md')+'#'+rid}
            status=row['status'] if n==4 else {'PASS':'通过','FAIL':'失败','BLOCKED':'阻塞','进行中':'未执行'}.get(row['status'],row['status'])
            if n==4 and status not in ('已完成','失败','阻塞'):
                pending.append({'id':rid,'status':row['status'],'title':row['object'],'prose':row.get('body',row.get('_prose',''))});continue
            fields={f:'' for f in FIELDS[n] if f not in ('失败原因','阻塞原因','处理建议','可行方向')}
            if n==4:
                fields.update({'任务缘由':_field(row,'problem',row.get('body','')),'行动要求':_field(row,'requirement',row.get('body','')),
                    '验收标准':_field(row,'criterion',row.get('body','')),'风险说明':'风险说明尚需结合本项实际保护范围完成内容复核',
                    '执行结果':'原生清单记录为'+status+'；具体结果依对应验收和原始证据核对'})
                locked={'status':status,'任务缘由':fields['任务缘由'],'行动要求':fields['行动要求'],'验收标准':fields['验收标准']}
            else:
                fields.update({'对应任务':'、'.join(row.get('refs',[])),'验收方式':_field(row,'context')+'；'+_field(row,'action'),
                    '预期结果':_field(row,'expected'),'实际结果':_field(row,'actual'),'关联证据':_field(row,'evidence')})
                locked={'status':status,'验收方式':fields['验收方式'],'对应任务':fields['对应任务'],'预期结果':fields['预期结果'],'实际结果':fields['实际结果'],'关联证据':fields['关联证据']}
                for locator in re.findall(r'(?:evidence/)[A-Za-z0-9_./-]+',fields['关联证据']):
                    path=inside(turn,locator,must_exist=True);artifact=path.read_bytes()
                    eid='artifact-'+str(len(all_evidence)+1)
                    if locator not in all_evidence:all_evidence[locator]=eid
                    else:eid=all_evidence[locator]
                    full=path.relative_to(root).as_posix();h=__import__('hashlib').sha256(artifact).hexdigest();hashes[full]=h
                    s['evidence'][eid]={'digest':h,'locator':full}
            if status in ('失败','阻塞'):
                fields[status+'原因']=_field(row,'actual',row.get('body','')) or '具体原因尚未得到完整记录'
                fields['处理建议']='沿用原始判据核对本项原因；证据不足时保留当前状态，不据此登记通过'
            rec={'id':rid,'title':row['object'],'status':status,'fields':fields,'locked':locked,'fact_refs':[fid],
                 'evidence_refs':[],'record_refs':row.get('refs',[]) if n==6 else [],'explanations':{}}
            if n==4:rec['required_tests']=[tid for tid,refs in test_refs.items() if rid in refs]
            if draft:
                old=next((r for r in draft['sections'][n-1].get('records',[]) if r['id']==rid),None)
                if old:
                    for key,val in old.get('fields',{}).items():
                        if key not in locked and key not in ('对应任务','关联证据','实际结果'):fields[key]=copy.deepcopy(val)
                    rec['explanations']=copy.deepcopy(old.get('explanations',{}))
            records.append(rec)
        if pending:
            # Keep source identities and native statuses; never relabel progress as failure.
            if records:pending += [{'id':r['id'],'status':r['status'],'title':r['title'],'prose':s['facts']['native-'+r['id']]['value'].get('body','')} for r in records]
            pending=sorted(pending,key=lambda r:[x['id'] for x in rows].index(r['id']))
            reason='本区保留全部原生目标与实际状态；已完成 '+str(sum(r['status']=='已完成' for r in rows))+' 项，其余继续按原承诺验收，不因部分目标仍在推进而撤销已证实结果；当前记录：'+'；'.join(x['id']+' '+x['title']+'，'+x['status'] for x in pending)
            s['sections'][n-1]={'number':n,'applicability':'unverified','reason':reason,'pending_source':pending,'source_items':[x['id'] for x in pending]}
        elif records:s['sections'][n-1]={'number':n,'records':records,'source_items':[r['id'] for r in records]}
    if manifest:
        files=[{**{k:x[k] for k in ('path','change')},'text':'实际文件与本轮封存前像有差异，类型依据存在状态和内容摘要确定'} for x in manifest]
        result='逐项变更均来自实际文件读取和本轮最早封存前像比较'
        if draft:
            old=next((r for r in draft['sections'][4].get('records',[]) if r.get('id')=='MOD-01'),None)
            if old:
                descriptions={(x.get('path'),x.get('change')):x.get('text') for x in old.get('fields',{}).get('修改对象',[]) if isinstance(x,dict)}
                for item in files:
                    text=descriptions.get((item['path'],item['change']))
                    if isinstance(text,str) and text.strip():item['text']=text
                result=old.get('fields',{}).get('修改结果',result)
        s['sections'][4]={'number':5,'source_items':['MOD-01'],'records':[{'id':'MOD-01','title':'本轮声明范围内的实际文件变更','fields':{'对应任务':'；'.join(r['id']+' '+r['object'] for r in cls),'修改对象':files,'修改结果':result,'动态扩展':''},'record_refs':[r['id'] for r in cls],'fact_refs':['native-manifest'],'evidence_refs':[]}]}
    if s['evidence']:
        records=[]
        for locator,eid in all_evidence.items():
            linked=[r for r in tests if locator in _field(r,'evidence')]
            refs=[r['id'] for r in linked];rid='EV-'+str(len(records)+1).zfill(2)
            rec={'id':rid,'title':'原生验收引用的证据 '+str(len(records)+1),'fact_refs':['native-'+r for r in refs],
                'evidence_refs':[eid],'record_refs':refs,'fields':{'关联事项':'；'.join(r['id']+' '+r['object']+'：'+_field(r,'purpose') for r in linked),
                '证据来源':[{'evidence_id':eid,'text':'该材料由当前原生验收条目实际引用，报告保存前重新读取其字节并核对摘要'}],
                '证明内容':'当前验收记录的实际观察为：'+'；'.join(_field(r,'actual') for r in linked),
                '核对情况':'引用路径、当前文件字节与保存的证据摘要已绑定；该绑定证明引用的是当前材料，材料中的业务事实仍须按原判据复核',
                '动态扩展':''}}
            if draft:
                old=next((r for r in draft['sections'][6].get('records',[]) if r['id']==rid),None)
                if old:
                    for key in ('证明内容','核对情况','动态扩展'):rec['fields'][key]=old.get('fields',{}).get(key,rec['fields'][key])
                    source_rows=old.get('fields',{}).get('证据来源',[])
                    for src in source_rows:
                        if src.get('evidence_id')==eid and isinstance(src.get('text'),str):rec['fields']['证据来源'][0]['text']=src['text']
            records.append(rec)
        s['sections'][6]={'number':7,'records':records,'source_items':[r['id'] for r in records]}
        for rec in s['sections'][5].get('records',[]):
            linked=[r['id'] for r in records if rec['id'] in r['record_refs']]
            if linked:
                value='、'.join(linked)+'；'+rec['fields']['关联证据']
                rec['fields']['关联证据']=value;rec['locked']['关联证据']=value
    s['facts']['native-manifest']={'value':manifest,'source_ref':rel+'/evidence/plan-revision-*.json'}
    registry_rel='.agent-project-control/reporting/quality/term-registry.json'
    registry_path=root/registry_rel
    if registry_path.is_file():
        registry=json.loads(_read(root,registry_rel,hashes))
        if registry.get('schema')!='apcf.term-registry/1':raise ContractError('TERM_REGISTRY_INVALID')
        keys={__import__('unicodedata').normalize('NFKC',k).upper():k for k in registry['entries']}
        verified={k:registry['entries'][raw] for k,raw in keys.items() if registry['entries'][raw].get('status') in ('VERIFIED','USER_CONFIRMED')}
        s['verified_term_registry']=verified
        for term in s['sections'][2].get('terms',[]):
            key=__import__('unicodedata').normalize('NFKC',term.get('registry_key',term.get('abbreviation',''))).upper()
            definition=verified.get(key)
            if definition:
                term.update(english=definition['english'],chinese=definition['chinese'],
                    kind='abbreviation' if definition.get('formal_acronym_expansion') else 'term' if not term.get('abbreviation') else 'local_alias',
                    definition_source=registry_rel+'#'+keys[key])
    # Hash actual source bytes and source-controlled order, not an Agent-supplied digest.
    s['native_sources']=hashes;s['source_digest']=digest({'identity':identity,'sources':hashes,'facts':s['facts'],'manifest':manifest})
    return s


class NativeReportWriter:
    def __init__(self,root,turn,request_id,captured):
        self.root=Path(root).resolve();self.turn=safe_turn(self.root,turn);self.request_id=request_id
        self.captured=copy.deepcopy(captured);self.store=Store(self.root)
        self.home=self.store.home/'quality';self.receipt_path=self.turn/'evidence/report-quality-publication.json'
        self.before_turn=(self.turn/'TURN.md').read_bytes();p=self.root/'CURRENT.md';self.before_current=p.read_bytes() if p.exists() else None

    def save_report(self,*,markdown,snapshot,expected_source_digest,report_digest,quality):
        assert_same_authority(snapshot,self.captured)
        if expected_source_digest!=self.captured['source_digest'] or digest(snapshot)!=report_digest:raise ContractError('SOURCE_BINDING_CHANGED')
        errors=[i for i in validate(snapshot) if i.severity=='error']
        if errors:raise ContractError('INVALID_SNAPSHOT')
        verify_artifact(markdown,snapshot)
        with self.store.guard():
            self.store._recover()
            if not sources_unchanged(self.root,self.captured['native_sources']):raise ContractError('NATIVE_SOURCE_CHANGED')
            previous=json.loads(self.receipt_path.read_text('utf-8-sig')) if self.receipt_path.is_file() else None
            if previous:
                if previous['identity']!=snapshot['identity']:raise ContractError('FOREIGN_REVISION')
                if snapshot['revision']<previous['revision']:raise ContractError('LATE_REVISION')
                if snapshot['revision']==previous['revision']:
                    if previous['report_digest']!=report_digest:raise ContractError('REVISION_COLLISION')
                    self.read_saved_report(previous);return previous
            elif snapshot['revision']!=1:raise ContractError('FIRST_REVISION_REQUIRED')
            if previous and snapshot['revision']!=previous['revision']+1:raise ContractError('REVISION_GAP')
            receipt={'schema':VERSION,'identity':snapshot['identity'],'request_id':self.request_id,'revision':snapshot['revision'],
                'source_digest':expected_source_digest,'report_digest':report_digest,'markdown_sha256':text_digest(markdown),
                'quality':quality,'persisted':True,'business_finalized':False}
            durable=self.turn/'evidence'/('report-quality-snapshot-r'+str(snapshot['revision'])+'.json')
            receipt['snapshot_path']=durable.relative_to(self.root).as_posix()
            archive=self.home/(report_digest+'.json');row={'receipt':receipt,'snapshot':snapshot}
            if archive.exists() and json.loads(archive.read_text('utf-8'))!=row:raise ContractError('REVISION_COLLISION')
            if durable.exists() and json.loads(durable.read_text('utf-8'))!=row:raise ContractError('REVISION_COLLISION')
            projections=[]
            for path,payload in ((archive,row),(durable,row),(self.receipt_path,receipt)):
                encoded=(json.dumps(payload,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
                projections.append({'path':path.relative_to(self.root).as_posix(),'before':path.read_bytes() if path.is_file() else None,'after':encoded})
                if path.is_relative_to(self.turn):
                    metadata=path.with_name(path.name+'.apcf-meta.yaml')
                    meta=('# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\nsha256: '+__import__('hashlib').sha256(encoded).hexdigest()+'\n').encode('utf-8')
                    projections.append({'path':metadata.relative_to(self.root).as_posix(),'before':metadata.read_bytes() if metadata.is_file() else None,'after':meta})
            committed=self.store.publish(self.turn,markdown,request_id=self.request_id,sources={k:v for k,v in self.captured['native_sources'].items() if v is not None},
                before_turn=self.before_turn,before_current=self.before_current,projections=projections)
            self.read_saved_report(receipt)
            return receipt

    def read_saved_report(self,receipt):
        if receipt.get('identity')!=self.captured['identity'] or receipt.get('request_id')!=self.request_id:raise ContractError('NATIVE_RECEIPT_IDENTITY_CHANGED')
        path=inside(self.root,receipt['snapshot_path'],must_exist=True)
        if path!=self.turn/'evidence'/('report-quality-snapshot-r'+str(receipt['revision'])+'.json'):raise ContractError('FOREIGN_SNAPSHOT')
        durable=json.loads(path.read_text('utf-8-sig'))
        if digest(durable['snapshot'])!=receipt['report_digest'] or any(receipt.get(k)!=v for k,v in durable['receipt'].items()):raise ContractError('NATIVE_RECEIPT_CHANGED')
        current=report_text((self.root/'CURRENT.md').read_text('utf-8-sig'));turn=report_text((self.turn/'TURN.md').read_text('utf-8-sig'))
        meta=published_meta((self.root/'CURRENT.md').read_text('utf-8-sig'))
        if current!=turn or text_digest(current)!=receipt['markdown_sha256'] or meta.get('source_turn')!=self.turn.relative_to(self.root).as_posix():raise ContractError('NATIVE_SAVE_READBACK_MISMATCH')
        return current

    def last_report(self):
        if not self.receipt_path.is_file():return None
        receipt=json.loads(self.receipt_path.read_text('utf-8-sig'))
        self.read_saved_report(receipt)
        return receipt


def sources_unchanged(root,sources):
    import hashlib
    for rel,expected in sources.items():
        path=inside(root,rel)
        if expected is None:
            if path.exists():return False
        elif not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:return False
    return True
