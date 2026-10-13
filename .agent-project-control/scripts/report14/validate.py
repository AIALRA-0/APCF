# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
from dataclasses import dataclass, asdict
import re
from .contract import CONTRACT, SECTIONS, EMPTY, MAX_RECORDS
from .markdown import parse, inline, literal, fields, records, body, children

ID = re.compile(r'(?<![A-Za-z0-9_-])(CL|MOD|TEST|EV|RES|LIM|UA|Q|NEXT)-\d{2,}(?![A-Za-z0-9_-])')
PLACEHOLDER = re.compile(r'<(?:约束|案例|案例说明|案例主题|状态|[^<>\n]{0,30}(?:ID|路径|字段|填写|标题|目标|名称|内容|方向一|方向二|方向三))[^<>\n]*>|\b(?:TODO|TBD|FIXME)\b|\[(?:待填写|在此填写)[^\]]*\]')

@dataclass
class Finding:
    code: str
    section: int
    line: int
    end_line: int
    message: str
    field: str = ''
    record: str = ''
    severity: str = 'error'
    category: str = 'structure'
    def json(self): return asdict(self)

@dataclass
class Result:
    findings: list[Finding]
    record_count: dict
    @property
    def ok(self): return not any(x.severity == 'error' for x in self.findings)
    def json(self): return {'ok':self.ok, 'findings':[x.json() for x in self.findings], 'counts':self.record_count,
                           'assurance':'structure_and_explicit_bindings_only'}

def validate(text: str, context: dict | None = None) -> Result:
    context = context or {}
    errs=[]; definitions={}; associations=[]; counts={}; test_links=[]
    def err(code,s,line,end,msg,field='',record='',category='structure'):
        errs.append(Finding(code,s,line,end,msg,field,record,category=category))
    try: doc=parse(text)
    except Exception:
        return Result([Finding('R14-PARSE',0,0,0,'无法按已定义的 Markdown 结构解析')],{})
    expected=list(range(1,15)); found=[s.number for s in doc.sections]
    if found != expected:
        err('R14-SECTIONS',0,0,len(doc.lines),'主标题须按1—14依次出现且各出现一次')
    for node in doc.nodes:
        if not doc.sections or (node.map and node.map[0] < doc.sections[0].line):
            if node.type != 'html_block' or not re.fullmatch(r'(?:<!-- APCF-[\s\S]*?-->\s*)+',node.content):
                err('R14-PREFIX',0,node.map[0] if node.map else 0,node.map[1] if node.map else 1,'正式报告前不可插入未定义正文')
    for node in doc.nodes:
        if node.type == 'fence':
            last=doc.lines[node.map[1]-1].strip() if node.map[1] else ''
            if not re.fullmatch(re.escape(node.markup[0])+r'{'+str(len(node.markup))+r',}',last):
                sec=next((s.number for s in doc.sections if s.line<=node.map[0]<s.end),0)
                err('R14-FENCE',sec,node.map[0],node.map[1],'代码围栏未闭合')
    # Teach-only labels and placeholders are never valid in presentation, even in code.
    protected={i for n in doc.nodes if n.type in ('fence','code_block') for i in range(n.map[0],n.map[1])}
    for i,line in enumerate(doc.lines):
        if i in protected and not re.search(r'<(?:约束|案例|案例说明|案例主题)[：:（]',line):continue
        if PLACEHOLDER.search(line) or re.match(r'^### (格式模板|填写案例)\s*$',line):
            sec=next((s.number for s in doc.sections if s.line <= i < s.end),0)
            err('R14-PLACEHOLDER',sec,i,i+1,'正式输出包含教学标记或未填写占位符')
    def empty_section(s):
        b=''.join(doc.lines[s.body_line:getattr(s,'core_end',s.end)]).strip()
        empty=(not b or b.rstrip('。') in EMPTY or bool(re.fullmatch(r'(?:本轮无相关事项|本轮不适用|当前尚无足够记录确认本区内容)[：；].+',b,re.S)))
        if empty and context.get('required_sections',[]) and s.number in context['required_sections']:
            err('R14-COVERAGE',s.number,s.line,s.end,'当前任务已要求此区内容，不能以空白或无事项代替',category='binding')
        return empty
    def validate_fields(s,rec,spec):
        fs=rec['fields']; names=[f['name'] for f in fs]; rid=rec.get('id','')
        required=[f for f in spec['fields'] if f not in spec.get('conditional_fields',[])]
        status=rec.get('status')
        if status in ('失败','阻塞'):
            required += [status+'原因','处理建议']
        if s.number==13 and context.get('required_directions',{}).get(rid): required+=['可行方向']
        for name in required:
            if name not in names:
                err('R14-FIELD-MISSING',s.number,rec['line'],rec['end'],f'缺少字段：{name}',name,rid)
        for name in set(names):
            if names.count(name)>1:
                err('R14-FIELD-DUPLICATE',s.number,rec['line'],rec['end'],f'字段重复：{name}',name,rid)
        order=[spec['fields'].index(n) for n in names if n in spec['fields']]
        if order != sorted(order): err('R14-FIELD-ORDER',s.number,rec['line'],rec['end'],'字段顺序不符',record=rid)
        for f in fs:
            name=f['name']; value=f['value'].strip()
            if name not in spec['fields']:
                err('R14-FIELD-UNKNOWN',s.number,f['line'],f['end'],f'未定义字段或层级错误：{name}',name,rid)
            if name in ('失败原因','阻塞原因') and name != str(status)+'原因':
                err('R14-CONDITIONAL',s.number,f['line'],f['end'],'原因字段与当前状态不符',name,rid)
            if name=='处理建议' and s.number in (4,6) and status not in ('失败','阻塞'):
                err('R14-CONDITIONAL',s.number,f['line'],f['end'],'通过或已完成条目不填写失败处理字段',name,rid)
            nested=spec.get('nested',{}).get(name)
            if not value and not f['lists'] and name not in spec.get('nullable_fields',[]):
                err('R14-FIELD-EMPTY',s.number,f['line'],f['end'],'字段需要真实内容或明确的未验证说明',name,rid)
            if nested:
                if value or len(f['lists'])!=1:
                    err('R14-NESTED',s.number,f['line'],f['end'],'父字段须独占一行，下一层列出内容',name,rid)
                else: validate_nested(s,rec,f,nested)
            elif f['lists']:
                err('R14-UNEXPECTED-NESTING',s.number,f['line'],f['end'],'此字段只使用一级BP正文，额外内容放动态扩展',name,rid)
            for a in ID.finditer(value): associations.append((a[0],s.number,f['line'],f['end'],name,rid))
            if name=='关联记录':
                kinds=[m[1] for m in ID.finditer(value)]
                rank={v:i for i,v in enumerate(CONTRACT['reference_order'])}
                ranks=[rank.get(k,99) for k in kinds]
                if ranks != sorted(ranks):err('R14-REF-ORDER',s.number,f['line'],f['end'],'关联顺序应为 CL → MOD → TEST → EV',name,rid)
            if s.number==6 and name=='对应任务':
                test_links.extend((rid,m[0]) for m in ID.finditer(value) if m[1]=='CL')
        for n in rec['nodes']:
            if n.type not in ('bullet_list',):
                # Extensions are explicitly allowed only after all NEXT records.
                if s.number==14 and n.type=='heading' and inline(n)=='补充材料':break
                err('R14-RECORD-STRAY',s.number,n.map[0],n.map[1],'条目正文必须归入规定字段',record=rid)
    changes=[]
    def validate_nested(s,rec,f,kind):
        lst=f['lists'][0]; items=lst.children; rid=rec.get('id','')
        wanted='ordered_list' if kind=='ordered' else 'bullet_list'
        if lst.type!=wanted: err('R14-LIST-TYPE',s.number,f['line'],f['end'],'列表类型不符合约束',f['name'],rid)
        if not items:err('R14-NESTED-EMPTY',s.number,f['line'],f['end'],'需要至少一个真实条目',f['name'],rid)
        vals=[]
        for j,item in enumerate(items,1):
            if any(n.type in ('bullet_list','ordered_list') for n in item.children):
                err('R14-LIST-DEPTH',s.number,item.map[0],item.map[1],'不允许第三层列表',f['name'],rid)
            raw=inline(item).strip(); vals.append(raw)
            if not raw:err('R14-EMPTY-ITEM',s.number,item.map[0],item.map[1],'列表子项不能为空',f['name'],rid)
            if kind=='ordered':
                line=doc.lines[item.map[0]]; m=re.match(r'^\s*(\d+)[.)]\s+',line)
                if not m or int(m[1])!=j:err('R14-STEP-SEQUENCE',s.number,item.map[0],item.map[1],'操作步骤从1连续编号',f['name'],rid)
            elif kind=='changes':
                m=re.fullmatch(r'【(新增|修改|删除|移动|重命名)】`([^`\n]+)`(?:\s*→\s*`([^`\n]+)`)?：([\s\S]+)',raw)
                if not m:err('R14-CHANGE',s.number,item.map[0],item.map[1],'变更需类型、代码样式路径与说明',f['name'],rid)
                else:
                    if m[1] in ('移动','重命名') and not m[3]:err('R14-MOVE-PAIR',s.number,item.map[0],item.map[1],'移动或重命名需要旧路径与新路径',f['name'],rid)
                    changes.append((m[3] or m[2],m[1],m[2]))
            elif kind=='sources':
                if not re.match(r'^(?:`[^`]+`|\[[^\]]+\]\([^\n]+\)|https?://\S+|[^\n：]+)：\S',raw):
                    err('R14-SOURCE',s.number,item.map[0],item.map[1],'来源需可定位位置与内容说明',f['name'],rid)
        if kind=='feedback':
            labels=[v.split('：',1)[0] for v in vals]
            if labels != ['返回模型','本地留存','异常反馈']:
                err('R14-FEEDBACK',s.number,f['line'],f['end'],'反馈使用返回模型、本地留存、异常反馈三个子字段',f['name'],rid)
    for s in doc.sections:
        if s.number not in SECTIONS:continue
        spec=SECTIONS[s.number]
        if s.title!=spec['title']:err('R14-TITLE',s.number,s.line,s.body_line,'章节名称不符')
        if doc.lines[s.line].rstrip('\r\n')!=spec['heading']:err('R14-HEADING',s.number,s.line,s.body_line,'主标题使用固定二级标题格式')
        if s.number==14:
            extension=[i for i,n in enumerate(s.nodes) if n.type=='heading' and n.tag=='h3' and inline(n)=='补充材料']
            if len(extension)>1:err('R14-EXTENSION',14,s.line,s.end,'补充材料最多出现一次')
            if extension:
                ix=extension[0];s.core_end=s.nodes[ix].map[0];append_nodes=s.nodes[ix+1:]
                for a in append_nodes:
                    if a.type=='heading' and a.tag in ('h1','h2','h3') or a.type=='paragraph' and inline(a).startswith('**【'):
                        err('R14-EXTENSION',14,a.map[0],a.map[1],'补充材料不可声明新主结构或记录身份')
                s.nodes=s.nodes[:ix]
        if empty_section(s):counts[str(s.number)]=0;continue
        if spec['kind']=='records':
            rs,orphans=records(s);counts[str(s.number)]=len(rs)
            if len(rs)>MAX_RECORDS:err('R14-LIMIT',s.number,s.line,s.end,'单章条目超出明确资源上限');continue
            for rec in rs:
                parts=rec['parts'];expected_parts=3 if spec['statuses'] else 2
                if len(parts)!=expected_parts:
                    err('R14-RECORD-TITLE',s.number,rec['line'],rec['title_node'].map[1],'条目标题格式不符');continue
                rid=parts[-2]; status=parts[0] if expected_parts==3 else None
                rec['id']=rid;rec['status']=status
                if not re.fullmatch(re.escape(spec['prefix'])+r'-\d{2,}',rid):err('R14-ID',s.number,rec['line'],rec['end'],'编号类型或数字位数不符',record=rid)
                if rid in definitions:err('R14-ID-DUPLICATE',s.number,rec['line'],rec['end'],'编号重复，不能自动重编号掩盖身份冲突',record=rid)
                definitions[rid]={'section':s.number,'status':status,'fields':{f['name']:f['value'] for f in rec['fields']},'record':rec}
                if status and status not in spec['statuses']:err('R14-STATUS',s.number,rec['line'],rec['end'],'状态不在该类记录允许的中文枚举中',record=rid)
                validate_fields(s,rec,spec)
            overview=spec.get('overview')
            if overview:
                candidates=[n for n in orphans if n.type=='paragraph' and inline(n).startswith('**'+overview+'**：')]
                if len(candidates)!=1:err('R14-OVERVIEW',s.number,s.body_line,s.end,'必须有且只有一个数字总览')
                else:
                    raw=inline(candidates[0]).split('：',1)[1]
                    numbers={};bad=False
                    for part in raw.split('；'):
                        m=re.fullmatch(r'([^：]+)：(\d+)',part.strip())
                        if not m or m[1] in numbers:bad=True;break
                        numbers[m[1]]=int(m[2])
                    if s.number in (4,6):
                        target={spec['prefix']+' 总数':len(rs),**{status:sum(r.get('status')==status for r in rs) for status in spec['statuses']}}
                        if bad or numbers!=target:err('R14-STATS',s.number,candidates[0].map[0],candidates[0].map[1],'总览须仅包含与实际条目一致的数量')
                    else:
                        unique={}
                        for path,kind,old in changes:
                            if path in unique and unique[path]!=kind:err('R14-CHANGE-CONFLICT',5,s.line,s.end,'同一文件存在矛盾的变更类型')
                            unique[path]=kind
                        target={'MOD 总数':len(rs),'变更文件总数':len(unique)}
                        target.update({kind:sum(v==kind for v in unique.values()) for kind in CONTRACT['changes'] if kind in unique.values()})
                        if bad or any(numbers.get(k)!=v for k,v in target.items()) or any(k not in target and (k not in CONTRACT['changes'] or v!=0) for k,v in numbers.items()):
                            err('R14-STATS',5,candidates[0].map[0],candidates[0].map[1],'变更总览须按唯一文件去重，移动/重命名计一个文件')
            for n in orphans:
                if overview and n.type=='paragraph' and inline(n).startswith('**'+overview+'**：'):continue
                err('R14-STRAY',s.number,n.map[0],n.map[1],'本区正文需使用对应条目结构或明确无事项说明')
            if not rs and not overview:err('R14-NO-RECORDS',s.number,s.line,s.end,'未识别到规定的记录条目')
        elif s.number==1:
            gs={g['title']:g for g in spec['groups']}; current=None; gs_seen=[]; subnodes=[]
            def finish_header():
                if current:
                    flds=fields(subnodes); g=gs[current]; r={'id':current,'line':start,'end':end,'fields':flds,'nodes':subnodes}
                    sp={'fields':g['fields'],'conditional_fields':g['optional_fields'],'nullable_fields':['动态扩展']}
                    validate_fields(s,r,sp)
            start=end=s.body_line
            for n in s.nodes:
                m=re.fullmatch(r'\*\*(.+?)\*\*：',inline(n)) if n.type=='paragraph' else None
                if m:
                    end=n.map[0];finish_header();subnodes=[];current=m[1];start=n.map[0]
                    if current not in gs:err('R14-HEADER-GROUP',1,start,n.map[1],'状态头出现未定义分组');current=None
                    else:gs_seen.append(current)
                else:subnodes.append(n)
            end=s.end;finish_header()
            expected_groups=[g['title'] for g in spec['groups']]
            order=[expected_groups.index(g) for g in gs_seen]
            if not gs_seen or order != sorted(set(order)):err('R14-HEADER-ORDER',1,s.line,s.end,'状态头分组按模板顺序且不能重复')
        elif s.number==2:
            hs=[n for n in s.nodes if n.type=='heading']
            if [inline(n) for n in hs]!=[f'2.{i}. {t}' for i,t in enumerate(spec['subheadings'],1)] or any(n.tag!='h3' for n in hs):
                err('R14-HANDOFF',2,s.line,s.end,'承上启下保留2.1—2.4四个三级标题')
            for i,n in enumerate(hs):
                stop=hs[i+1].map[0] if i+1<len(hs) else s.end
                if not ''.join(doc.lines[n.map[1]:stop]).strip():err('R14-PROSE-EMPTY',2,n.map[0],stop,'承接段落需要实际正文')
            for n in s.nodes:
                if n.type not in ('heading','paragraph'):err('R14-PROSE',2,n.map[0],n.map[1],'承上启下采用完整自然段')
        elif s.number==3:
            for n in s.nodes:
                if n.type!='bullet_list':err('R14-TERMS',3,n.map[0],n.map[1],'术语表使用一级BP');continue
                for item in n.children:
                    if any(x.type!='paragraph' for x in item.children):err('R14-TERM-NESTING',3,item.map[0],item.map[1],'术语禁止二次缩进和子字段')
                    if not re.match(r'^.+?（[^（）]+）：[\s\S]+$',inline(item).replace('**','')):
                        err('R14-TERM-NAME',3,item.map[0],item.map[1],'术语须准确名称（英文）后接解释')
        elif s.number==10:
            hs=[n for n in s.nodes if n.type=='heading']
            if not hs:err('R14-EXPLANATION',10,s.line,s.end,'完整说明需10.1起连续主题小节')
            for i,n in enumerate(hs,1):
                if n.tag!='h3' or not re.match(rf'^10\.{i}\. \S',inline(n)):err('R14-SUBSEQUENCE',10,n.map[0],n.map[1],'小节从10.1连续编号，标题可随任务调整')
                stop=hs[i].map[0] if i<len(hs) else s.end
                if not ''.join(doc.lines[n.map[1]:stop]).strip():err('R14-PROSE-EMPTY',10,n.map[0],stop,'小节没有说明正文')
            for n in s.nodes:
                if n.type in ('bullet_list','ordered_list'):err('R14-PROSE',10,n.map[0],n.map[1],'完整说明正文采用自然段，不套用BP属性表')
        elif s.number==11:
            groups=[]
            for n in s.nodes:
                if n.type=='paragraph' and re.fullmatch(r'\*\*[^\n]+：[^\n]+\*\*',inline(n)):
                    groups.append({'line':n.map[0],'end':s.end,'nodes':[]})
                elif groups:groups[-1]['nodes'].append(n)
                else:err('R14-KEYPOINT-TITLE',11,n.map[0],n.map[1],'要点用加粗的主题：核心判断标题')
            for g in groups:
                g['fields']=fields(g['nodes']); validate_fields(s,g,{'fields':['关键事实','实际含义'],'nullable_fields':[]})
            if not groups:err('R14-KEYPOINT',11,s.line,s.end,'未识别关键要点结构')
    ext=context.get('external_records',{})
    for rid,s,l,e,f,owner in associations:
        if rid not in definitions and rid not in ext:
            err('R14-REF-MISSING',s,l,e,f'关联记录不存在或未从真实记录加载：{rid}',f,owner,'binding')
    for tid,cid in test_links:
        c=definitions.get(cid,ext.get(cid,{}));t=definitions.get(tid,{})
        if c.get('status')=='已完成' and t.get('status') in ('失败','阻塞','未执行'):
            r=t['record'];err('R14-STATE-CONFLICT',6,r['line'],r['end'],'已完成任务关联到未通过的当前必需验收',record=tid,category='binding')
    for prefix,allowed in context.get('record_sets',{}).items():
        for rid,info in definitions.items():
            if rid.startswith(prefix+'-') and rid not in allowed:
                r=info['record'];err('R14-UNBOUND-RECORD',info['section'],r['line'],r['end'],'记录不在已加载的真实账本中',record=rid,category='binding')
    for rid,expected in context.get('records',{}).items():
        actual=definitions.get(rid)
        if actual is None:
            n=expected.get('section',4);s=next((x for x in doc.sections if x.number==n),None)
            err('R14-RECORD-COVERAGE',n,s.line if s else 0,s.end if s else len(doc.lines),'已存在的真实任务记录不得被省略',record=rid,category='binding');continue
        r=actual['record']
        if expected.get('status') and actual.get('status')!=expected['status']:
            err('R14-STATUS-BINDING',actual['section'],r['line'],r['end'],'报告状态与已加载的真实记录不符',record=rid,category='binding')
        for f,v in expected.get('immutable_fields',{}).items():
            if actual['fields'].get(f,'').strip()!=v.strip():
                err('R14-IMMUTABLE',actual['section'],r['line'],r['end'],'原定要求或验收标准不得被改写',f,rid,'binding')
    for token in context.get('forbidden_phrases',[]):
        if token and token in doc.text:err('R14-EXAMPLE-LEAK',0,0,len(doc.lines),'出现与真实项目无关的教学案例内容',category='binding')
    # Explicit factual equivalence only, not claims of semantic truth certification.
    for s in doc.sections:
        if s.number==1:
            txt=body(doc,s)
            for prefix,n in [('CL',4),('TEST',6)]:
                matches=re.findall(prefix+r' 总数：(\d+)',txt)
                if any(int(v)!=counts.get(str(n),0) for v in matches):err('R14-HEADER-STATS',1,s.line,s.end,'状态头统计与正文条目数不一致',category='binding')
            it=re.search(r'- IT 编号及标题：(IT-\d+)',txt);parent=re.search(r'- 所属 IT：(IT-\d+)',txt)
            if it and parent and it[1]!=parent[1]:err('R14-IT-LINK',1,s.line,s.end,'当前TR所属IT与当前IT不一致',category='binding')
    return Result(errs,counts)
