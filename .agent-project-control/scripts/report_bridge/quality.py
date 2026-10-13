# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import re
from collections import Counter
from .contract import Issue, digest

DESCRIPTIVE={'任务缘由','行动要求','风险说明','验收标准','执行结果','验收方式','预期结果','实际结果','失败原因','阻塞原因','处理建议','证明内容','核对情况','实际成果','结果判定','交付情况','当前限制','实际影响','解除条件','操作缘由','当前基础','待明确问题','推进安排','明确条件','承接结果','推荐理由','下轮目标','预期交付'}
ROLES={
 '任务缘由':['具体对象与当前情景','需要处理的差异','差异对实际目标的影响'],
 '行动要求':['具体处理对象','承诺动作与必要范围','原有保护边界'],
 '风险说明':['风险怎样触发','影响哪个对象或结果','必要保护或真实无特殊风险'],
 '验收标准':['可观察条件','预期结果','与行动及已识别风险的关系'],
 '执行结果':['实际完成工作','实际结果及原定要求的关系','剩余边界'],
 '核对情况':['实际比较对象','核对方式','已观察结果及缺口'],
 '证明内容':['原始材料中的事实','支持的具体判断','证明边界'],
 '实际影响':['受到影响的对象','具体使用后果','事实和可能后果的区别']}


def prose_length(text:str)->int:
    """Do not credit huge file paths, identifiers or markdown boilerplate as depth."""
    text=re.sub(r'`[^`]*`','',text)
    text=re.sub(r'(?:https?://|[A-Za-z]:[/\\])\S+','',text)
    return len(re.sub(r'\s','',text))


def assess(snapshot:dict,minimum=90)->list[Issue]:
    issues=[]; repeats={}
    for si,sec in enumerate(snapshot['sections']):
        for ri,r in enumerate(sec.get('records',[])):
            for f,text in r.get('fields',{}).items():
                if not isinstance(text,str) or not text.strip() or f not in DESCRIPTIVE:continue
                p=f'/sections/{si}/records/{ri}/fields/{f}'
                extra=r.get('explanations',{}).get(f,'')
                if extra:
                    text=text+'；'+extra
                if f in r.get('locked',{}) and f in r.get('explanations',{}):
                    p=f'/sections/{si}/records/{ri}/explanations/{f}'
                # A probe proposes review; it cannot certify semantic adequacy.
                # Explicit source-backed short/no-special-risk fields are judged by
                # the independent reviewer instead of padded to a universal length.
                exception=r.get('short_field_basis',{}).get(f)
                bound_short=isinstance(exception,dict) and exception.get('fact_ref') in r.get('fact_refs',[]) and bool(exception.get('reason'))
                if prose_length(text)<minimum and not bound_short:
                    issues.append(Issue('QUALITY_SHORT',p,'描述性字段偏短；补足字段职责，而不是机械填充字数','review'))
                if re.search(r'本案例(?:只|用于|旨在)|本示例(?:只|用于)|不对应其他章节|教学(?:目的|意图)',text):
                    issues.append(Issue('QUALITY_META_COMMENT',p,'删除跳出业务情景的教学注释','review'))
                key=re.sub(r'\s','',text)
                if key in repeats:issues.append(Issue('QUALITY_DUPLICATE',p,'跨记录逐字复用解释：'+repeats[key],'review'))
                repeats[key]=p
                clauses=[x.strip() for x in re.split('[；。]',text) if len(x.strip())>=12]
                if len(clauses)!=len(set(clauses)):issues.append(Issue('QUALITY_PADDING',p,'同一条目重复句子，长度不能代替信息','review'))
                if f=='证明内容':
                    sources=r.get('fields',{}).get('证据来源',[])
                    if isinstance(sources,list) and any(text==x.get('text') for x in sources):
                        issues.append(Issue('QUALITY_SOURCE_COPY',p,'来源说明不能直接代替证明关系','review'))
        if sec['number']==10 and sec.get('applicability','applicable')=='applicable':
            for j,sub in enumerate(sec.get('subsections',[])):
                text=''.join(sub.get('paragraphs',[]))
                if prose_length(text)<160:issues.append(Issue('QUALITY_EXPLANATION_SHORT',f'/sections/{si}/subsections/{j}','补充必要机制、取舍或验证解释；不是强制六个小节','review'))
    return issues


def review_request(snapshot:dict,rules:list,positive_examples:list)->dict:
    return {'kind':'semantic-review','source_digest':snapshot['source_digest'],
      'report_digest':digest(snapshot),'rubric_digest':digest(rules),
      'instructions':('仅评估文本职责、可读性、因果链、重复及事实支持；指出具体字段和缺失内容。'
      '案例是风格锚点，不是事实。长度和关键词只用于发现问题，不能独自认定质量合格。'
      '不能新增执行事实、升级验收结果、改动项目权限或判据。'),
      'rules':rules,'anchors':positive_examples,'report':snapshot,
      'response_contract':{'source_digest':'same','report_digest':'same','rubric_digest':'same',
         'model_id':'actual','issues':[{'pointer':'/sections/...','reason':'具体差异','required_roles':['missing role']}],
         'assessed_pointers':['/sections/...'],'quality':'adequate|needs_revision|insufficient_facts'}}


def accept_review(review:dict,request:dict,required_pointers:list[str])->tuple[bool,str]:
    if not isinstance(review,dict):return False,'review_not_object'
    for key in ['source_digest','report_digest','rubric_digest']:
        if review.get(key)!=request[key]:return False,'stale_or_wrong_review_binding'
    if not review.get('model_id'):return False,'model_identity_missing'
    if not set(required_pointers).issubset(set(review.get('assessed_pointers',[]))):return False,'incomplete_review_coverage'
    return review.get('quality')=='adequate' and review.get('issues')==[], 'model_review_not_truth_certificate'
