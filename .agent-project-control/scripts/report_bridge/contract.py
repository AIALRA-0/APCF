# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import hashlib, json, re, unicodedata
from dataclasses import dataclass, asdict
from typing import Any

VERSION='apcf.report-observation/1'
TITLES=['精确状态头','承上启下','术语表','执行清单','文件修改','验收摘要','关键证据','结果状态','剩余限制','完整说明','关键要点','用户需要执行','需要继续讨论、搜索或决策','下一步推荐']
FIELDS={
 4:['任务缘由','行动要求','风险说明','验收标准','执行结果','失败原因','阻塞原因','处理建议','动态扩展'],
 5:['对应任务','修改对象','修改结果','动态扩展'],
 6:['对应任务','验收方式','预期结果','实际结果','失败原因','阻塞原因','处理建议','关联证据','动态扩展'],
 7:['关联事项','证据来源','证明内容','核对情况','动态扩展'],
 8:['对应目标','实际成果','结果判定','交付情况','关联记录','动态扩展'],
 9:['当前限制','实际影响','解除条件','关联记录','动态扩展'],
 12:['操作缘由','操作步骤','完成判据','反馈与记录','关联记录','动态扩展'],
 13:['事项性质','当前基础','待明确问题','可行方向','推进安排','预期返回','明确条件','关联记录','动态扩展'],
 14:['承接结果','推荐理由','下轮目标','建议下轮输入','预期交付','关联记录','动态扩展']}
PREFIX={4:'CL',5:'MOD',6:'TEST',7:'EV',8:'RES',9:'LIM',12:'UA',13:'Q',14:'NEXT'}
STATES={4:['已完成','失败','阻塞'],6:['通过','失败','阻塞','未执行']}
FILE_TYPES=['新增','修改','删除','移动','重命名']
HEX=re.compile(r'^[a-f0-9]{64}$')
IDENT=re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$')
# These two expansions are explicitly confirmed by the user. Others require a
# repository-backed registry entry rather than invented official expansions.
TERMS={'IT':{'english':'Iteration','chinese':'迭代','source':'user-confirmed'},
       'EV':{'english':'Evidence','chinese':'证据','source':'user-confirmed'}}

@dataclass(frozen=True)
class Issue:
    code:str
    pointer:str
    message:str
    severity:str='error'
    def to_dict(self): return asdict(self)

class ContractError(ValueError): pass

def canonical(value:Any)->bytes:
    """Shared Python/TS canonical format: sorted UTF-16 keys; safe integers only.

    Floating-point numbers are deliberately excluded. Measurement values are
    decimal strings with units. Do not call this an implementation of JCS.
    """
    def check(v):
        if v is None or type(v) in (bool,str):
            if isinstance(v,str) and any(0xD800<=ord(c)<=0xDFFF for c in v):
                raise ContractError('unpaired surrogate is not accepted')
        elif type(v) is int:
            if abs(v)>9007199254740991: raise ContractError('unsafe integer')
        elif isinstance(v,list):
            for x in v:check(x)
        elif isinstance(v,dict):
            if not all(type(k) is str for k in v):raise ContractError('nonstring key')
            for k,x in v.items():check(k);check(x)
        else:raise ContractError('unsupported canonical type')
    check(value)
    def emit(v):
        if isinstance(v,dict):
            keys=sorted(v,key=lambda k:k.encode('utf-16-be'))
            return '{'+','.join(emit(k)+':'+emit(v[k]) for k in keys)+'}'
        if isinstance(v,list):return '['+','.join(emit(x) for x in v)+']'
        return json.dumps(v,ensure_ascii=False,separators=(',',':'),allow_nan=False)
    return emit(value).encode('utf-8')

def digest(value:Any)->str:return hashlib.sha256(canonical(value)).hexdigest()
def text_digest(text:str)->str:return hashlib.sha256(text.replace('\r\n','\n').encode()).hexdigest()
def normalized(value):
    import unicodedata
    value = unicodedata.normalize("NFKC", str(value)).casefold()
    return "".join(c for c in value if unicodedata.category(c) != "Cf" and c.isalnum())

def term_issues(term:dict,registry:dict|None=None,pointer='/term')->list[Issue]:
    out=[]; registry=TERMS if registry is None else registry
    a=term.get('abbreviation','');en=term.get('english','');zh=term.get('chinese','')
    kind=term.get('kind','term')
    if not all(isinstance(x,str) for x in [a,en,zh]):return [Issue('TERM_TYPE',pointer,'术语字段必须是字符串')]
    if not zh.strip() or not en.strip():out.append(Issue('TERM_EMPTY',pointer,'缺少中英文名称'))
    if a and normalized(a)==normalized(en):out.append(Issue('TERM_SELF_EXPANSION',pointer,'缩写不能以自身作为英文展开'))
    if a and normalized(a)==normalized(zh):out.append(Issue('TERM_CHINESE_SELF',pointer,'中文名称不能仅重复缩写'))
    rule=registry.get(a.upper())
    if a and rule and normalized(en)!=normalized(rule['english']):out.append(Issue('TERM_WRONG_EXPANSION',pointer,'英文展开与已确认术语登记不一致'))
    if a and not rule and kind=='abbreviation':out.append(Issue('TERM_UNVERIFIED',pointer,'未登记缩写须提供可核对的定义来源','review'))
    if kind=='local_alias' and not term.get('definition_source'):out.append(Issue('TERM_ALIAS_SOURCE',pointer,'项目简称需要定义来源','review'))
    return out

def safe_relative(path:str)->bool:
    return bool(isinstance(path,str) and path and not re.match(r'^(?:[A-Za-z]:|[/\\]|[a-z]+://)',path) and not any(x in ('..','') for x in path.replace('\\','/').split('/')))

def walk_text(value:Any,pointer=''):
    if isinstance(value,str):yield pointer,value
    elif isinstance(value,list):
        for i,v in enumerate(value):yield from walk_text(v,f'{pointer}/{i}')
    elif isinstance(value,dict):
        for k,v in value.items():yield from walk_text(v,f'{pointer}/{k}')

# Inline text is not permitted to manufacture report structure or executable HTML.
# Paragraph breaks are supported by the renderer with the correct list indent.
def inline_issues(text:str,pointer:str)->list[Issue]:
    out=[]
    if re.search(r'<(?:约束|案例|填写案例|案例说明)[：:（(]',text):out.append(Issue('GUIDANCE_LEAK',pointer,'生成指导标签不能进入正式报告'))
    if re.search(r'(?mi)^\s*(?:#{1,6}\s|```|~~~|[-*+]\s|\d+\.\s)',text):out.append(Issue('TEXT_STRUCTURE',pointer,'字段文本不得嵌入另一条结构'))
    if re.search(r'<\s*(?:script|iframe|object|embed|img|svg|style)\b|javascript\s*:',text,re.I):out.append(Issue('UNSAFE_MARKUP',pointer,'不接受可执行或外链载入标记'))
    return out

def validate(snapshot:dict,registry:dict|None=None)->list[Issue]:
    """Validate typed report facts/structure. Semantic truth is a separate review."""
    issues=[]
    def err(c,p,m):issues.append(Issue(c,p,m))
    if not isinstance(snapshot,dict):return [Issue('ROOT_TYPE','/','报告必须是对象')]
    if registry is None and 'verified_term_registry' in snapshot:registry=snapshot['verified_term_registry']
    if snapshot.get('schema')!=VERSION:err('SCHEMA','/schema','需要显式当前格式版本；不按正文自动降级')
    identity=snapshot.get('identity',{})
    for key in ['project_id','producer_id','iteration_id','turn_id']:
        if not isinstance(identity.get(key),str) or not IDENT.fullmatch(identity[key]):err('IDENTITY','/identity/'+key,'缺少合法、显式绑定的身份')
    for k in ['revision']:
        if type(snapshot.get(k)) is not int or snapshot[k]<1:err('REVISION','/'+k,'修订必须为正整数')
    if not isinstance(snapshot.get('source_digest'),str) or not HEX.fullmatch(snapshot['source_digest']):err('SOURCE_DIGEST','/source_digest','需要真实来源快照摘要')
    sections=snapshot.get('sections',[])
    if not isinstance(sections,list) or [s.get('number') for s in sections if isinstance(s,dict)]!=list(range(1,15)):
        err('SECTION_ORDER','/sections','章节必须按1至14固定顺序');return issues
    facts=snapshot.get('facts',{})
    if not isinstance(facts,dict):err('FACTS_TYPE','/facts','事实登记必须为对象');facts={}
    evidence=snapshot.get('evidence',{})
    if not isinstance(evidence,dict):err('EVIDENCE_TYPE','/evidence','证据登记必须为对象');evidence={}
    for fid,f in facts.items():
        if not isinstance(f,dict) or 'value' not in f or not f.get('source_ref'):err('FACT_PROVENANCE',f'/facts/{fid}','事实须携带来源定位')
    for eid,e in evidence.items():
        if not isinstance(e,dict) or not HEX.fullmatch(str(e.get('digest',''))) or not e.get('locator'):err('EVIDENCE_BINDING',f'/evidence/{eid}','证据须绑定内容摘要和定位')
    all_ids={}; refs=[]; unique_files={}
    for si,sec in enumerate(sections):
        n=si+1;p=f'/sections/{si}'
        if sec.get('title',TITLES[si])!=TITLES[si]:err('SECTION_TITLE',p+'/title','章节名称不可改变')
        applicability=sec.get('applicability','applicable')
        if applicability not in ['applicable','none','not_applicable','unverified']:err('APPLICABILITY',p,'非法适用性')
        if applicability!='applicable':
            if not sec.get('reason'):err('EMPTY_REASON',p+'/reason','无事项、不适用或未验证需要真实依据')
            if sec.get('records') or sec.get('terms') or sec.get('paragraphs'):err('EMPTY_WITH_CONTENT',p,'空章节不能同时包含正式记录')
            pending=sec.get('pending_source')
            if sec.get('source_items') and not (applicability=='unverified' and n==4 and isinstance(pending,list)
                    and [r.get('id') for r in pending]==sec['source_items']
                    and all(r.get('status') in ('未开始','进行中','已完成','失败','阻塞','不适用') and r.get('prose') for r in pending)):
                err('ERASED_SOURCE',p,'已有来源记录不得降为空章节')
            elif pending:
                for row in pending:
                    rid=row.get('id','')
                    if not re.fullmatch(r'CL-\d{2,}',rid) or rid in all_ids:err('DUPLICATE_ID',p,'待验收源身份缺失或重复')
                    all_ids[rid]=(4,row)
            continue
        records=sec.get('records',[])
        if n in FIELDS:
            if not records:err('MISSING_RECORDS',p,'适用章节需要记录')
            expected=sec.get('source_items')
            if expected is None:err('SOURCE_ORDER_MISSING',p+'/source_items','必须由账本适配器给出来源顺序')
            elif [r.get('id') for r in records]!=expected:err('SOURCE_ORDER',p,'记录顺序必须与已绑定账本一致')
            for ri,r in enumerate(records):
                q=f'{p}/records/{ri}';rid=r.get('id','')
                if not isinstance(rid,str) or not re.fullmatch(PREFIX[n]+r'-\d{2,}',rid):err('RECORD_ID',q,'记录编号非法')
                if rid in all_ids:err('DUPLICATE_ID',q,'编号重复')
                all_ids[rid]=(n,r)
                if not r.get('title'):err('RECORD_TITLE',q,'缺少单一目标标题')
                status=r.get('status')
                if n in STATES and status not in STATES[n]:err('STATE_ENUM',q+'/status','禁止把进行中等状态静默映射为失败')
                fields=r.get('fields',{})
                if not isinstance(fields,dict):err('FIELDS',q,'字段应为对象');continue
                needed=[f for f in FIELDS[n] if f not in ['失败原因','阻塞原因','处理建议','可行方向']]
                if n==13 and '可行方向' not in fields:pass
                if n in [4,6] and status in ['失败','阻塞']:needed += [status+'原因','处理建议']
                for f in needed:
                    if f not in fields:err('MISSING_FIELD',q+'/fields/'+f,'缺少规定字段')
                for f,v in fields.items():
                    fp=q+'/fields/'+f
                    if f not in FIELDS[n]:err('UNKNOWN_FIELD',fp,'附加信息请放动态扩展，不改变固定字段')
                    if f in ['失败原因','阻塞原因'] and f!=str(status)+'原因':err('CAUSE_STATE',fp,'原因字段与实际状态不一致')
                    if isinstance(v,str):
                        issues+=inline_issues(v,fp)
                        if not v.strip() and f not in ['动态扩展','关联记录']:err('EMPTY_REQUIRED',fp,'必需字段不能为空')
                    elif isinstance(v,list):
                        for j,item in enumerate(v):
                            if not isinstance(item,dict):err('LIST_ITEM',fp+'/'+str(j),'嵌套条目需要结构化数据');continue
                            if f=='修改对象':
                                path=item.get('path','');kind=item.get('change')
                                if not safe_relative(path):err('FILE_PATH',fp,'文件必须使用安全项目相对路径')
                                if kind not in FILE_TYPES:err('FILE_CHANGE',fp,'非法变更类型')
                                if path in unique_files:
                                    err('FILE_CONFLICT' if unique_files[path]!=kind else 'FILE_DUPLICATE',fp,'同一文件不可重复计入修改对象')
                                unique_files[path]=kind
                                if kind in ['移动','重命名'] and not safe_relative(item.get('previous_path','')):err('FILE_ORIGIN',fp,'移动或重命名须保留原路径')
                            elif f=='证据来源':
                                if item.get('evidence_id') not in evidence:err('EVIDENCE_REF',fp,'证据ID未绑定实际材料')
                            if not item.get('text') and f not in ['关联记录']:err('LIST_TEXT',fp+'/'+str(j),'缺少条目解释')
                            elif isinstance(item.get('text'),str):issues+=inline_issues(item['text'],fp+'/'+str(j)+'/text')
                    else:err('FIELD_TYPE',fp,'字段必须为文本或合法列表')
                for ef,ev in r.get('explanations',{}).items():
                    ep=q+'/explanations/'+ef
                    if ef not in FIELDS[n] or not isinstance(ev,str):err('EXPLANATION_FIELD',ep,'解释只能补充既有文本字段')
                    elif ev:issues+=inline_issues(ev,ep)
                for fid in r.get('fact_refs',[]):
                    if fid not in facts:err('FACT_REF',q,'引用事实不存在')
                for eid in r.get('evidence_refs',[]):
                    if eid not in evidence:err('EVIDENCE_REF',q,'引用证据不存在')
                refs.extend((q,x) for x in r.get('record_refs',[]))
                bound=r.get('locked',{})
                for key,value in bound.items():
                    if key=='status' and status!=value:err('LOCKED_STATE',q,'状态与来源账本不一致')
                    if key!='status' and fields.get(key)!=value:err('LOCKED_REQUIREMENT',q+'/fields/'+key,'源账本原句不得被生成或修复覆盖')
        if n==3:
            for ti,t in enumerate(sec.get('terms',[])):
                issues+=term_issues(t,registry,f'{p}/terms/{ti}')
                if not t.get('description'):err('TERM_DESCRIPTION',f'{p}/terms/{ti}','术语缺少解释')
                else:issues+=inline_issues(t['description'],f'{p}/terms/{ti}/description')
        if n in [2,10]:
            subs=sec.get('subsections',[])
            if n==2 and [x.get('title') for x in subs]!=['上轮进展','本轮动因','本轮处理','当前落点']:err('HANDOFF_STRUCTURE',p,'承上启下必须保留四段职责')
            if n==10 and not subs:err('EXPLANATION_EMPTY',p,'缺少完整说明')
            for j,s in enumerate(subs):
                if not s.get('paragraphs') or not s.get('title'):err('SUBSECTION_EMPTY',p,'小节缺少标题或正文')
        for ptr,text in walk_text(sec,p):
            if any(x in ptr for x in ['/fields/','/source_items','/locked/']):continue
            if ptr.endswith('/text') or '/paragraphs/' in ptr or ptr.endswith('/reason'):issues+=inline_issues(text,ptr)
    for p,rid in refs:
        if rid not in all_ids:err('DANGLING_REFERENCE',p,'关联记录不存在：'+str(rid))
    # Cross-record links may be many-to-many; no index or cardinality assumptions.
    counts={4:{s:0 for s in STATES[4]},6:{s:0 for s in STATES[6]}}
    for _,(n,r) in all_ids.items():
        if n in counts and r.get('status') in counts[n]:counts[n][r['status']]+=1
    for n in [4,6]:
        claimed=sections[n-1].get('counts')
        if claimed is not None and claimed!=counts[n]:err('COUNTS',f'/sections/{n-1}/counts','统计必须由当前记录自动派生')
    header=sections[0].get('summaries',{})
    for key,n in [('CL',4),('TEST',6)]:
        if key in header and header[key]!=counts[n]:err('HEADER_COUNTS','/sections/0/summaries/'+key,'状态头分项统计与正文不一致')
    fm=sections[4].get('file_counts')
    derived={k:list(unique_files.values()).count(k) for k in FILE_TYPES};derived['total']=len(unique_files)
    if fm is not None and fm!=derived:err('FILE_COUNTS','/sections/4/file_counts','明细与统计不一致；请核对来源清单而非迎合数字')
    manifest=snapshot.get('change_manifest')
    if manifest is not None:
        wanted={x['path']:x['change'] for x in manifest}
        if len(wanted)!=len(manifest) or wanted!=unique_files:err('FILE_MANIFEST','/change_manifest','修改对象未完整对应真实去重变更清单')
    for _,(n,r) in all_ids.items():
        if n==4 and r.get('status')=='已完成':
            for test_id in r.get('required_tests',[]):
                test=all_ids.get(test_id)
                if not test or test[0]!=6 or test[1].get('status')!='通过':err('COMPLETION_TESTS','/records/'+r['id'],'完成结论依赖的验收尚未通过')
    return issues
