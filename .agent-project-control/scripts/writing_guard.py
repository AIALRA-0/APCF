# APCF-META {"schema":1,"visibility":"public"}
"""Task-bound writing checks, not a proof of model understanding or host interception.

The glossary is a flat BP carrier. Historical ledgers keep their original bytes.
Only exact standalone APCF transport comments outside protected blocks are removed
from reader output, after the original report has passed its existing validators.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CONTRACT = 'writing-reliability-1'
ROOT = Path(__file__).resolve().parents[2]
CONTROL = ROOT / '.agent-project-control'
CARD = '.agent-project-control/standards/RULE-ACTIVATION-v0.1.md'
EXAMPLES = '.agent-project-control/standards/WRITING-MINIMAL-EXAMPLES.md'
TOP = re.compile(r'^#{1,4}\s+([0-9])\.(?![0-9])\s*(.*?)\s*$', re.M)
BP = re.compile(r'^- \*\*(.+?)\*\*：(.+)$')
CJK = re.compile(r'[\u3400-\u9fff]')
LATIN = re.compile(r'(?<![A-Za-z0-9_])[A-Za-z][A-Za-z0-9]*(?:[-/][A-Za-z0-9]+)*(?![A-Za-z0-9_])')
META = re.compile(r'^<!-- APCF-(META|GOAL|FACTS) (\{.*\}) -->$')
MARKERS = re.compile(r'^<!-- APCF-(?:TEST-FORMAT v[123]|GOAL-FORMAT v1) -->$')
PLACEHOLDERS = {'略','同上','已解释','相关','当前使用','用于本轮','已经审核','通过','解释内容','定义内容','直观类比','同前文'}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalize(text: str) -> str:
    return text.lstrip('\ufeff').replace('\r\n','\n').replace('\r','\n')


def read(path: Path) -> str:
    return normalize(path.read_text(encoding='utf-8-sig'))


def text_hash(text: str) -> str:
    return digest(normalize(text).encode('utf-8'))


def visible_lines(text: str):
    """Yield (line number, raw, protected); never unprotect literal fences/quotes."""
    fence=None
    for number,line in enumerate(normalize(text).splitlines(),1):
        match=re.match(r'^\s*(`{3,}|~{3,})',line)
        if fence:
            yield number,line,True
            if match and match[1][0]==fence[0] and len(match[1])>=len(fence):fence=None
        elif match:
            fence=match[1];yield number,line,True
        else:yield number,line,bool(re.match(r'^\s*>',line))


def reader_view(text: str) -> str:
    """Preserve all visible prose. Not a general HTML/comment sanitizer."""
    lines=[]
    for _,line,protected in visible_lines(text):
        if not protected:
            if MARKERS.fullmatch(line.strip()):continue
            m=META.fullmatch(line.strip())
            if m:
                try:row=json.loads(m[2])
                except ValueError as e:raise ValueError('invalid APCF transport comment') from e
                if not isinstance(row,dict):raise ValueError('invalid APCF transport comment value')
                if m[1] in {'GOAL','FACTS'}:
                    # Whole report validation checks spans; this function never invents replacements.
                    expected=1 if m[1]=='GOAL' else 3
                    if row.get('schema')!=expected or not re.fullmatch(r'[0-9a-f]{64}',str(row.get('sha256',''))) or not isinstance(row.get('spans'),dict):
                        raise ValueError('malformed report fact mapping')
                elif row.get('schema')!=1:raise ValueError('unknown metadata schema')
                continue
            if '<!-- APCF-' in line:raise ValueError('unknown or inline APCF metadata cannot be silently removed')
        lines.append(line)
    return '\n'.join(lines).strip()+'\n'


def section(text: str, number: int) -> tuple[str,int]:
    """Locate a report section without stripping away meaningful indentation."""
    matches=[m for m in TOP.finditer(normalize(text))]
    found=[(i,m) for i,m in enumerate(matches) if int(m[1])==number]
    if len(found)!=1:return '',0
    i,m=found[0];end=matches[i+1].start() if i+1<len(matches) else len(text)
    return text[m.end():end],text[:m.end()].count('\n')


def glossary(text: str) -> tuple[list[dict],list[str]]:
    """Every real glossary term is a top-level titled BP, not a child definition."""
    body,offset=section(normalize(text),2)
    errors=[];entries=[];seen=set()
    for line_no,line,protected in visible_lines(body):
        if not line.strip():continue
        label=f'术语表第 {offset+line_no} 行'
        if protected:
            errors.append(label+'：术语表不能用代码块或引用块代替实际一级 BP');continue
        m=BP.fullmatch(line)
        if not m:
            errors.append(label+'：必须直接使用 - **术语名称**：连续定义，禁止引导段、二次缩进和裸术语列表');continue
        title,definition=m[1].strip(),m[2].strip()
        if title in seen:errors.append(label+'：重复术语标题')
        seen.add(title)
        # Slash outside a verified official name is not an excuse to merge objects.
        outside=re.sub(r'（[^）]*）|`[^`]+`','',title)
        if re.search(r'[/／]|\s+&\s+',re.sub(r'(?<![A-Za-z])[A-Z]/[A-Z](?![A-Za-z])','',outside)):errors.append(label+'：不同对象必须独立列项，不能合写标题')
        if not definition or definition in PLACEHOLDERS:errors.append(label+'：定义不能用占位短语代替')
        if '。' in definition:errors.append(label+'：生成中文正文含禁用句号')
        if re.search(r'(?:定义|用途|原理|类比)\s*[：:]',definition):errors.append(label+'：不要把连续定义拆成短字段')
        if not CJK.search(title) and not re.fullmatch(r'`[^`]+`',title):
            errors.append(label+'：英文名称应有真实中文说明，机器标识才使用原样代码格式')
        if re.fullmatch(r'[A-Za-z][A-Za-z0-9 /-]*[\u3400-\u9fff].*',title) and '（' not in title:
            # Internal identifiers are adjudicated using their actual name_status below.
            pass
        entries.append({'title':title,'body':definition,'line':offset+line_no,'raw':line})
    return entries,errors


def prose_without_protected(text: str) -> str:
    out=[]
    for _,line,protected in visible_lines(text):
        if protected:out.append('');continue
        line=re.sub(r'<!--.*?-->','',line)
        line=re.sub(r'\]\((?:<[^>]*>|[^)]*)\)',']',line)
        line=re.sub(r'https?://[^\s)]+','',line)
        # Actual paths, flags, identifiers, numbers and statuses can be literal.
        # Plain `CI` or `Gate` is not automatically a machine-literal exemption.
        line=re.sub(r'`([^`]+)`',lambda m:' ' if re.search(r'[./_\x5c=]|^--|\d',m[1]) else m[1],line)
        line=re.sub(r'【(?:PASS|FAIL|BLOCKED|对应 CL-[^】]*|TEST-[^】]*|CL-[^】]*)】','',line)
        line=re.sub(r'(?<!\w)(?:IT|TR|CL|TEST|REG|PA|MAT|ADR|RB)-[0-9A-Za-z_-]+|\b[WSDR]\d{2}\b|\bv\d+(?:\.\d+)+\b',' ',line)
        out.append(line)
    return '\n'.join(out)


def _nonempty(value: Any) -> bool:
    return isinstance(value,str) and bool(value.strip()) and value.strip() not in PLACEHOLDERS


def content_errors(text: str, review: dict | None = None) -> list[str]:
    """Mechanical named checks plus exact review excerpts; never semantic certification."""
    text=normalize(text);entries,errors=glossary(text)
    if review is None:
        return errors
    if not isinstance(review,dict):return errors+['术语复核记录必须是对象']
    aliases=[];covered_titles=set();restricted_exemptions=[]
    for group in [*review.get('items',[]),*review.get('manual_terms',[])]:
        if not isinstance(group,dict):errors.append('无效术语复核条目');continue
        term=group.get('term','')
        if not isinstance(term,str) or not term.strip():errors.append('空术语名');continue
        for meaning in group.get('meanings',[]):
            if not isinstance(meaning,dict):errors.append(term+'：无效定义记录');continue
            decision=meaning.get('decision')
            if decision!='EXPLAINED':
                if decision not in {'KNOWN_TO_AUDIENCE','LITERAL_FORMAT','OUT_OF_SCOPE'} or not _nonempty(meaning.get('reason')):
                    errors.append(term+'：未解释对象必须保留真实范围和理由')
                # Exemptions may reduce explanatory depth, never hide actual prose from checks.
                # Existing terminology_review separately authenticates the materialized source.
                if decision in {'LITERAL_FORMAT','OUT_OF_SCOPE'}:
                    restricted_exemptions.append(term)
                elif decision=='KNOWN_TO_AUDIENCE':
                    zh=meaning.get('chinese_name','');full=meaning.get('verified_full_name','')
                    kind=meaning.get('term_kind');status=meaning.get('name_status')
                    if kind=='abbreviation' and status=='VERIFIED' and _nonempty(zh) and _nonempty(full):
                        expected=f'{term} {zh}（{full}）'
                    elif kind in {'proper_name','concept'} and status=='VERIFIED' and _nonempty(zh) and _nonempty(full):
                        expected=f'{zh}（{full}）'
                    elif kind=='internal_identifier' and not full and _nonempty(zh):
                        expected=f'{term} {zh}'
                    elif CJK.search(term) and not re.search(r'[A-Za-z]',term):
                        expected=term
                    else:
                        errors.append(term+'：读者熟悉只允许减少解释深度，不能豁免首次名称结构或猜造全称')
                        continue
                    aliases.append((term,expected))
                    if full:aliases.append((full,expected))
                continue
            title=meaning.get('display_name','')
            hits=[e for e in entries if e['title']==title]
            if len(hits)!=1:errors.append(term+'：display_name 必须定位当前唯一一级 BP 标题');continue
            entry=hits[0];covered_titles.add(title);body=entry['body'];kind=meaning.get('term_kind');status=meaning.get('name_status')
            full=meaning.get('verified_full_name','');zh=meaning.get('chinese_name','')
            if kind=='abbreviation' and status=='VERIFIED':
                expected=f'{term} {zh}（{full}）'
                if not _nonempty(zh) or not CJK.search(zh) or title!=expected:errors.append(term+'：正式缩写必须采用 ABBR 中文名称（English Full Name）')
            elif kind in {'proper_name','concept'} and full:
                expected=f'{zh}（{full}）'
                if not _nonempty(zh) or title!=expected:errors.append(term+'：无缩写名称必须采用中文名称（English Name）')
            elif kind=='internal_identifier' or status=='UNVERIFIED':
                if full:errors.append(term+'：未确认或本地编号不得补造正式全称')
                if status=='UNVERIFIED' and (not _nonempty(meaning.get('name_limit')) or meaning['name_limit'] not in body):errors.append(term+'：未确认边界必须在正文中可见')
                if not (title.startswith(term+' ') and CJK.search(title)):errors.append(term+'：本地编号需直接附真实中文含义，不合并多个编号')
            elif kind=='literal':
                if title!=f'`{term}`' and not (title.startswith(term+' ') and CJK.search(title)):errors.append(term+'：机器名称保留原值，不编造全称')
            elif kind=='concept':
                if not CJK.search(title):errors.append(term+'：中文概念须有真实名称')
            else:errors.append(term+'：名称类型或已核实名称缺失')
            if status=='NOT_APPLICABLE' and kind=='abbreviation':errors.append(term+'：不确定全称不能冒充不适用')
            for key in ('definition','context_relevance','analogy'):
                val=meaning.get(key)
                if not _nonempty(val) or val not in body:errors.append(term+'：'+key+' 必须是可见定义的真实片段，不能只在 JSON 中补写')
            if not _nonempty(meaning.get('analogy_basis')):errors.append(term+'：类比对应什么及其边界需要具体复核，不以出现“像”字代替判断')
            if meaning.get('definition')==meaning.get('context_relevance'):errors.append(term+'：含义与本轮作用不能用同一占位串冒充')
            if not (term in title or full and term in full):errors.append(term+'：当前标题没有实际标识该术语')
            aliases.append((term,title))
            if full:aliases.append((full,title))
    for entry in entries:
        if entry['title'] not in covered_titles:errors.append(entry['title']+'：真实可见术语未被逐项复核')
    # First explanatory use, not compact machine status fields, determines name expansion.
    matches=list(TOP.finditer(text));filtered=text
    if matches and matches[0][1]=='0':
        end=matches[1].start() if len(matches)>1 else len(text);filtered='\n'*text[:end].count('\n')+text[end:]
    filtered=prose_without_protected(filtered)
    for term in restricted_exemptions:
        if re.search(r'(?<![A-Za-z0-9_])'+re.escape(term)+r'(?![A-Za-z0-9_])',filtered):
            errors.append(term+'：词条仍出现在实际说明性正文中，不能声明仅为受保护原文或不在范围内')
    covered=[]
    for term,title in aliases:
        if not re.search(r'[A-Za-z]',term):continue
        pattern=r'(?<![A-Za-z0-9_])'+re.escape(term)+r'(?![A-Za-z0-9_])'
        uses=list(re.finditer(pattern,filtered))
        if title and uses:
            first=uses[0];title_starts=[m.start() for m in re.finditer(re.escape(title.replace('`','')),filtered)]
            if not any(start<=first.start()<start+len(title.replace('`','')) for start in title_starts):
                errors.append(term+'：首次说明性出现没有使用已核实的完整名称结构，远处词表不能弥补')
        for m in uses:covered.append((m.start(),m.end()))
        if title:
            for m in re.finditer(re.escape(title.replace('`','')),filtered):covered.append((m.start(),m.end()))
    for m in LATIN.finditer(filtered):
        if not any(a<=m.start() and m.end()<=b for a,b in covered):
            errors.append(f'未复核的英文或缩写 {m[0]}：应解释、使用中文，或以实际依据说明保护范围')
    return list(dict.fromkeys(errors))


def candidate_hash(path: Path) -> str | None:
    if not path.is_file():return None
    if path.name=='TURN.md':
        from terminology_review import extract_user_report
        try:return text_hash(extract_user_report(read(path)))
        except ValueError:pass  # new Turn placeholder; not a validated report
    return digest(path.read_bytes())


def policy() -> dict:
    path=CONTROL/'standards/WRITING-ACTIVATION.lock.json'
    from repair_io import inside
    obj=json.loads(path.read_text(encoding='utf-8'))
    if obj.get('schema')!=1 or obj.get('contract')!=CONTRACT:raise ValueError('invalid writing activation policy')
    for rel,sha in obj['files'].items():
        if digest(inside(ROOT,rel,must_exist=True).read_bytes())!=sha:raise ValueError('写作来源变化：'+rel)
    return obj


def enabled(turn: Path) -> bool:
    p=Path(turn)/'evidence/execution-session.json'
    if not p.is_file():return False  # documented historical/read-only record
    row=json.loads(p.read_text(encoding='utf-8'))
    profile=row.get('writing_contract')
    if profile is None:return False  # existing pre-update session, not retrospectively rewritten
    if profile!=CONTRACT:raise ValueError('unknown writing contract; no downgrade')
    return True


def bind(turn: Path) -> None:
    from repair_io import private_json,lock
    from execution_session import load
    policy();row=load(turn)
    with lock(CONTROL/'runtime/tmp/.writing.lock'):
        path=Path(turn)/'evidence/execution-session.json'
        if row.get('writing_contract') not in {None,CONTRACT}:raise ValueError('unknown prior writing contract')
        row['writing_contract']=CONTRACT
        private_json(path,row)


def prepare(turn: Path, target: str, phase: str) -> dict:
    from repair_io import private_json,inside,lock
    from execution_session import load
    if not enabled(turn):raise ValueError('new writing requires binding the current Turn first')
    row=load(turn);pol=policy();path=inside(ROOT,target)
    if phase not in {'draft','review'}:raise ValueError('invalid writing phase')
    if phase=='review' and not path.is_file():raise ValueError('review requires the actual written candidate')
    statepath=Path(turn)/'evidence/writing.json'
    with lock(CONTROL/'runtime/tmp/.writing.lock'):
        state=json.loads(statepath.read_text(encoding='utf-8-sig')) if statepath.exists() else {'schema':1,'contract':CONTRACT,'targets':{}}
        fields={'request_id':row['request_id'],'nonce':row['nonce'],'policy_sha256':digest((CONTROL/'standards/WRITING-ACTIVATION.lock.json').read_bytes())}
        if state.get('request_id')!=row['request_id'] or state.get('nonce')!=row['nonce']:
            state={'schema':1,'contract':CONTRACT,'targets':{}}
        state.update(fields)
        material=read(ROOT/CARD).split('## 1.3. 设计规范（Design）')[0]+'\n'+read(ROOT/EXAMPLES)
        print(material);sys.stdout.flush()  # receipt follows completed output, not a claimed read
        item={'at':datetime.now(timezone.utc).isoformat(),'target_sha256':candidate_hash(path),'emitted_sha256':text_hash(material),**fields}
        t=state['targets'].setdefault(target,{})
        if phase=='draft':t.clear()
        t[phase]=item
        private_json(statepath,state)
    return item


def context_errors(turn:Path,target:str) -> list[str]:
    from repair_io import inside
    from execution_session import load
    errors=[]
    try:
        session=load(turn);policy();state=json.loads((Path(turn)/'evidence/writing.json').read_text(encoding='utf-8'))
        expected={'request_id':session['request_id'],'nonce':session['nonce'],'policy_sha256':digest((CONTROL/'standards/WRITING-ACTIVATION.lock.json').read_bytes())}
        t=state['targets'][target]
        for phase in ('draft','review'):
            if any(t.get(phase,{}).get(k)!=v for k,v in expected.items()):errors.append('写作前／复核前的短规则读取缺失或过期：'+phase)
        path=inside(ROOT,target,must_exist=True)
        if t.get('review',{}).get('target_sha256')!=candidate_hash(path):errors.append('复核后正文已改变，必须重新读取本轮短规则并审核实际成稿')
    except (OSError,ValueError,KeyError,TypeError) as exc:errors.append('写作阶段证据缺失或无效：'+str(exc))
    return errors


def report_errors(report:str,turn:Path) -> list[str]:
    try:
        if not enabled(turn):return []
        target=(Path(turn).resolve()/'TURN.md').relative_to(ROOT.resolve()).as_posix()
        errors=context_errors(turn,target)
        p=Path(turn)/'evidence/terms-review.json'
        if not p.is_file():return errors+content_errors(report)+['当前 terms-review.json 不存在，不能宣称术语审核通过']
        review=json.loads(p.read_text(encoding='utf-8'))
        # Existing validator checks all source evidence, SHA and observations.
        errors+=content_errors(report,review)
        return errors
    except (OSError,ValueError,KeyError,TypeError) as exc:return ['写作门禁拒绝：'+str(exc)]


def before_write(turn:Path,target:str,before:bytes|None)->None:
    if not enabled(turn) or Path(target).suffix.lower() not in {'.md','.txt','.rst'}:return
    from execution_session import load
    policy();r=load(turn);s=json.loads((Path(turn)/'evidence/writing.json').read_text(encoding='utf-8-sig'))
    d=s.get('targets',{}).get(target,{}).get('draft',{})
    for k,v in {'request_id':r['request_id'],'nonce':r['nonce'],'policy_sha256':digest((CONTROL/'standards/WRITING-ACTIVATION.lock.json').read_bytes())}.items():
        if d.get(k)!=v:raise ValueError('先读取本轮写作短规则，不能复用旧上下文')
    if d.get('target_sha256')!=(digest(before) if before is not None else None):raise ValueError('写作目标在准备后改变，请保留外部编辑并重新准备')


def main()->int:
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('bind');q.add_argument('--turn',required=True)
    q=sub.add_parser('prepare');q.add_argument('--turn',required=True);q.add_argument('--target',required=True);q.add_argument('--phase',choices=['draft','review'],required=True)
    q=sub.add_parser('check');q.add_argument('--report',required=True);q.add_argument('--review')
    q=sub.add_parser('reader-view');q.add_argument('--report',required=True);q.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        if a.command=='bind':bind(Path(a.turn));print('BOUND: current Turn, not host interception')
        elif a.command=='prepare':prepare(Path(a.turn),a.target,a.phase)
        elif a.command=='check':
            report=read(Path(a.report));review=json.loads(Path(a.review).read_text(encoding='utf-8-sig')) if a.review else None
            e=content_errors(report,review)
            if e:print('\n'.join('FAIL: '+x for x in e));return 2
            print('FORMAT_CHECKED' if review is None else 'FORMAT_AND_REVIEW_BINDINGS_CHECKED; not independent semantic certification')
        else:
            # Standalone view is not delivery approval; emit/Finalize use report_errors separately.
            from repair_io import exclusive
            exclusive(Path(a.output),reader_view(read(Path(a.report))).encode('utf-8'))
            print('VIEW_ONLY: not a Gate or publication authorization')
    except (OSError,ValueError,KeyError,TypeError) as exc:print('BLOCKED: '+str(exc));return 2
    return 0

if __name__=='__main__':raise SystemExit(main())
