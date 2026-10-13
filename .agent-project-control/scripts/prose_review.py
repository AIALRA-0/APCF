# APCF-META {"schema":1,"visibility":"public"}
"""Concrete visible-text review binding for TEST v3 reports.

No dictionary, minimum glossary length, fixed takeaway count, or independent-review
claim is manufactured here. The author must supply actual observations. Verification
is deliberately named STRUCTURE_AND_BINDING, not semantic correctness certification.
"""
from __future__ import annotations
import argparse
from report14.bindings import is14
from report14.bridge import keypoints
import hashlib
import json
from pathlib import Path
import re
from repair_io import canonical, digest, inside, normalized, private_json, text_digest
from narrative_contract import VACUOUS


def _content(value, label):
    if not isinstance(value, str) or value.strip() in VACUOUS:
        raise ValueError(label + ': a concrete review observation is required')
    return value


def quote(text: str, selection, label: str) -> str:
    if not isinstance(selection, dict) or set(selection) != {'start','end','sha256'}:
        raise ValueError(label+': expected Unicode-codepoint start/end and sha256')
    a, b = selection['start'], selection['end']
    if type(a) is not int or type(b) is not int or not 0 <= a < b <= len(text):
        raise ValueError(label+': invalid text range')
    value = text[a:b]
    if digest(value.encode()) != selection['sha256']:
        raise ValueError(label+': excerpt has changed')
    return value


def locate(text: str, exact: str) -> dict:
    if not exact or text.count(exact) != 1:
        raise ValueError('excerpt must have one occurrence; otherwise provide explicit positions')
    a = text.index(exact)
    return {'start':a, 'end':a+len(exact), 'sha256':digest(exact.encode())}


def explanation_units(report: str) -> list[dict]:
    """Stable paragraph units for coverage, not a claim that all paragraphs are key results."""
    from report_contract import split_sections
    _, sections = split_sections(report)
    body = sections.get(10 if is14(report) else 5, ('',''))[1]
    out=[]
    for para in re.split(r'\n\s*\n', body):
        para=para.strip()
        if not para or all(line.lstrip().startswith('#') for line in para.splitlines()):
            continue
        out.append({'id':f'E{len(out)+1:03d}', 'text':para, 'sha256':digest(para.encode())})
    return out


def _source(turn: Path, row: dict) -> bytes:
    if not isinstance(row, dict) or not isinstance(row.get('path'), str):
        raise ValueError('source reference missing')
    p = inside(turn, row['path'], must_exist=True)
    if not p.is_relative_to((turn/'evidence').resolve()):
        raise ValueError('observations must reference current-Turn evidence')
    data=p.read_bytes()
    if not data or row.get('sha256') != digest(data):
        raise ValueError('source absent, empty or stale: '+row['path'])
    return data


def _goal_digest(turn):
    from test_ledger import parse_checklist
    rows=parse_checklist((turn/'CHECKLIST.md').read_text(encoding='utf-8'))
    return digest(canonical([{k:r[k] for k in ('id','object','body')} for r in rows]))


def draft(report: str, turn: Path) -> dict:
    from test_ledger import parse_checklist, parse_tests
    report=normalized(report).strip()
    return {
        'schema':1, 'report_sha256':digest(report.encode()),
        'request_sha256':digest((turn/'REQUEST.md').read_bytes()), 'goal_digest':_goal_digest(turn),
        'reviewer': {'method':'author_self_review','identity':'','limits':'not an independent or human review'},
        'goals':[{'id':r['id'],'observation':''} for r in parse_checklist((turn/'CHECKLIST.md').read_text())],
        'tests':[{'id':r['id'],'evidence':[], 'actual_selection':None, 'observation':''} for r in parse_tests((turn/'TEST.md').read_text())],
        'explanation_coverage':[{'id':u['id'],'sha256':u['sha256'],'importance':'UNREVIEWED',
                               'takeaway_indexes':[], 'reason':''} for u in explanation_units(report)],
        'takeaways':[],
        'section_observations':{str(i):'' for i in (range(1,15) if is14(report) else range(10))},
        'findings':[],
    }


def validate(report: str, turn: Path, review: dict) -> list[str]:
    from report_contract import split_sections, BP_RE
    from test_ledger import parse_tests, parse_checklist
    report=normalized(report).strip(); turn=Path(turn)
    errors=[]
    try:
        if not isinstance(review,dict) or review.get('schema') != 1:
            raise ValueError('missing review schema')
        if review.get('report_sha256') != digest(report.encode()):
            raise ValueError('review is for another visible final report')
        if review.get('request_sha256') != digest((turn/'REQUEST.md').read_bytes()) or review.get('goal_digest') != _goal_digest(turn):
            raise ValueError('request or pre-execution goals differ from reviewed inputs')
        reviewer=review.get('reviewer',{})
        if reviewer.get('method') != 'author_self_review':
            raise ValueError('this local verifier cannot authenticate independent-agent/human identity; do not self-declare it')
        _content(reviewer.get('identity'), 'reviewer identity')
        _content(reviewer.get('limits'), 'review limitations')
        _,sections=split_sections(report)
        if len(sections)!=(14 if is14(report) else 10): raise ValueError('complete report missing')
        targets={'goals':parse_checklist((turn/'CHECKLIST.md').read_text(encoding='utf-8')),
                 'tests':parse_tests((turn/'TEST.md').read_text(encoding='utf-8'))}
        for kind, rows in targets.items():
            notes=review.get(kind)
            if not isinstance(notes,list) or [x.get('id') for x in notes]!=[r['id'] for r in rows]:
                errors.append(kind+': missing, extra, duplicated or reordered review target'); continue
            for src, note in zip(rows,notes):
                try:
                    _content(note.get('observation'),src['id'])
                    if kind=='tests':
                        actual=quote(src['_prose'],note.get('actual_selection'),src['id']+' visible actual result')
                        if actual != src['actual']:
                            raise ValueError(src['id']+': review must locate the complete actual-result clause, not a heading')
                        refs=note.get('evidence')
                        if not isinstance(refs,list) or not refs:
                            raise ValueError(src['id']+': actual evidence required (including why NOT_RUN/BLOCKED)')
                        for ref in refs:
                            data=_source(turn,ref)
                            if ref['path'] not in src['evidence']:
                                raise ValueError(src['id']+': evidence not cited in the visible TEST sentence')
                            # Observed text must actually be in the cited bytes, not hidden only in this JSON.
                            observation=_content(ref.get('excerpt'),'observed source excerpt')
                            if observation.encode('utf-8') not in data:
                                raise ValueError(src['id']+': quoted observation absent from evidence')
                    else:
                        selections=note.get('roles',{})
                        if set(selections)!={'context','problem','consequence','requirement','criterion'}:
                            raise ValueError(src['id']+': all causal goal roles must be reviewed')
                        for name,value in selections.items():
                            part=quote(src['body'],value,src['id']+'/'+name)
                            if part.strip() in VACUOUS: raise ValueError('retrospective/empty goal')
                except (ValueError, OSError, KeyError, TypeError) as exc: errors.append(str(exc))
        # Coverage is variable-length. Supplemental paragraphs are allowed but require a reason.
        units=explanation_units(report); coverage=review.get('explanation_coverage')
        if not isinstance(coverage,list) or [x.get('id') for x in coverage]!=[u['id'] for u in units]:
            errors.append('all explanation units must be classified, not just the first four')
            coverage=[]
        bullets=keypoints(report) if is14(report) else [line.strip() for line in sections[6][1].splitlines() if BP_RE.fullmatch(line.strip())]
        takeaways=review.get('takeaways',[])
        if not isinstance(takeaways,list) or len(takeaways)!=len(bullets):
            errors.append('every actual takeaway needs evidence-bound review, without a fixed quota')
            takeaways=[]
        covered=set()
        for u, item in zip(units,coverage):
            try:
                if item.get('sha256')!=u['sha256']: raise ValueError(u['id']+': stale explanation unit')
                _content(item.get('reason'),u['id']+' coverage reason')
                if item.get('importance') not in {'core','supporting'}: raise ValueError('unreviewed importance')
                refs=item.get('takeaway_indexes')
                if not isinstance(refs,list) or any(type(i)is not int or i<0 or i>=len(bullets) for i in refs):
                    raise ValueError('bad takeaway index')
                if item['importance']=='core' and not refs: raise ValueError(u['id']+': core conclusion/limit omitted from key points')
                covered.update(refs)
            except (ValueError,KeyError,TypeError) as exc: errors.append(str(exc))
        if set(range(len(bullets)))-covered: errors.append('takeaway added without a corresponding explanation conclusion')
        for index,note in enumerate(takeaways):
            try:
                if note.get('sha256')!=digest(bullets[index].encode()): raise ValueError('takeaway changed')
                _content(note.get('observation'),'takeaway observation')
                sources=note.get('source_units')
                if not isinstance(sources,list) or not sources or not set(sources)<={u['id'] for u in units}:
                    raise ValueError('takeaway source unit missing')
                for source in sources:
                    match=next((c for c in coverage if c['id']==source),{})
                    if index not in match.get('takeaway_indexes',[]): raise ValueError('takeaway coverage mapping is not reciprocal')
            except (ValueError,KeyError,TypeError) as exc: errors.append(str(exc))
        observations=review.get('section_observations',{})
        if set(observations)!={str(i) for i in (range(1,15) if is14(report) else range(10))}: errors.append('complete report review required, not only glossary')
        for section, note in observations.items():
            try: _content(note, 'section '+section)
            except ValueError as exc: errors.append(str(exc))
        findings=review.get('findings')
        if not isinstance(findings,list): errors.append('findings must be explicit')
        elif any(not isinstance(x,dict) or x.get('status') not in {'resolved','accepted_limit'} or not x.get('reason') for x in findings):
            errors.append('unresolved content findings remain')
    except (ValueError,OSError,KeyError,TypeError) as exc:
        errors.append(str(exc))
    return errors


def validate_review_file(report: str, turn: Path) -> list[str]:
    p=Path(turn)/'evidence/prose-review.json'
    try:
        return ['visible-content review: '+e for e in validate(report,Path(turn),json.loads(p.read_text(encoding='utf-8')))]
    except (OSError,ValueError) as exc:
        return ['visible-content review missing/invalid: '+str(exc)]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['init','check'])
    parser.add_argument('--turn',required=True)
    args=parser.parse_args();turn=Path(args.turn).resolve()
    from terminology_review import extract_user_report,read_report_text
    report=extract_user_report(read_report_text(turn/'TURN.md'))
    if args.command=='init':
        private_json(turn/'evidence/prose-review.json',draft(report,turn),create=True)
        print('UNREVIEWED: fill real quotes, observations, causal roles and conclusion coverage; no automatic PASS')
    else:
        errors=validate_review_file(report,turn)
        for e in errors: print('FAIL:',e)
        if errors: raise SystemExit(2)
        print('PASS_STRUCTURE_AND_BINDING: author review is concrete and current; semantic truth is not certified')

if __name__=='__main__': main()
