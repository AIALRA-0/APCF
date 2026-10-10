# APCF-META {"schema":1,"visibility":"public"}
"""TEST v3: one visible narrative + a hash-bound, non-value-duplicating span map.

Offsets are Unicode code points in NFC-neutral LF text, NOT JavaScript UTF-16 offsets.
This validates facts/locations, not universal natural-language quality.
"""
from __future__ import annotations
import json
import re
from repair_io import canonical, digest

TEST_MARKER = '<!-- APCF-TEST-FORMAT v3 -->'
GOAL_MARKER = '<!-- APCF-GOAL-FORMAT v1 -->'
FACT_PREFIX = '<!-- APCF-FACTS '
GOAL_PREFIX = '<!-- APCF-GOAL '
FIELDS = ('purpose', 'context', 'action', 'expected', 'actual', 'conclusion', 'evidence')
GOAL_FIELDS = ('context', 'problem', 'consequence', 'requirement', 'criterion')
HEAD = re.compile(r'^- 【(?P<status>未执行|进行中|PASS|FAIL|BLOCKED|不适用)】【(?P<id>TEST-[A-Za-z0-9_-]+)】【对应 (?P<refs>CL-[A-Za-z0-9_-]+(?:[、,， ]+CL-[A-Za-z0-9_-]+)*)】【(?P<object>[^】\r\n]+)】：(?P<body>[^\r\n]+)$')
GOAL_HEAD = re.compile(r'^- 【(?P<status>未开始|进行中|已完成|阻塞|不适用)】【(?P<id>CL-[A-Za-z0-9_-]+)】【(?P<object>[^】\r\n]+)】：(?P<body>[^\r\n]+)$')
# Explicit known counterexamples only. No minimum word count / mandatory connective words.
VACUOUS = {'', '略', '同上', '已完成', '代码已经改完，测试已通过', '已经改完，测试已通过',
           '通过', '良好', '当前', '执行', '全部良好', '全部符合规范', 'TODO', 'TBD', '...','…'}


def spans_for(prose: str, quotes: dict[str, str], fields=FIELDS) -> dict:
    if set(quotes) != set(fields):
        raise ValueError('fact fields missing/unknown')
    spans = {}
    for key in fields:
        quote = quotes[key]
        if not isinstance(quote, str) or not quote.strip() or prose.count(quote) != 1:
            raise ValueError(key + ': quote must occur exactly once; use explicit spans for repeated text')
        i = prose.index(quote)
        spans[key] = [i, i+len(quote)]
    return {'schema': 3 if fields == FIELDS else 1, 'sha256': digest(prose.encode()), 'spans': spans}


def validate_map(prose: str, mapping: dict, fields=FIELDS) -> dict[str, str]:
    if not isinstance(prose, str) or '\n' in prose or '\r' in prose or not prose.strip():
        raise ValueError('narrative must occupy one logical source line; visual wrapping is unrestricted')
    if not isinstance(mapping, dict) or set(mapping) != {'schema', 'sha256', 'spans'}:
        raise ValueError('only schema, sha256 and spans belong in the derived map')
    if type(mapping['schema']) is not int or mapping['schema'] != (3 if fields == FIELDS else 1) or mapping['sha256'] != digest(prose.encode()):
        raise ValueError('narrative changed; fact map is stale or has wrong schema')
    spans = mapping['spans']
    if not isinstance(spans, dict) or set(spans) != set(fields):
        raise ValueError('missing or unknown fact spans')
    result = {}
    for key, value in spans.items():
        if (not isinstance(value, list) or len(value) != 2 or any(type(n) is not int for n in value)
                or not 0 <= value[0] < value[1] <= len(prose)):
            raise ValueError('invalid Unicode code-point span: ' + key)
        result[key] = prose[value[0]:value[1]]
        if result[key].strip() in VACUOUS:
            raise ValueError(key + ': placeholder is not a specific fact')
    if fields == FIELDS and prose.startswith('版本／环境／前提：'):
        raise ValueError('new TEST prose must not be the old field-label serialization')
    return result


def parse_pair(line: str, comment: str, *, goal=False) -> dict:
    pattern = GOAL_HEAD if goal else HEAD
    prefix = GOAL_PREFIX if goal else FACT_PREFIX
    match = pattern.fullmatch(line.strip())
    if match is None or not comment.startswith(prefix) or not comment.endswith(' -->'):
        raise ValueError('malformed narrative record or missing bound map')
    row = match.groupdict()
    try:
        mapping = json.loads(comment[len(prefix):-4], object_pairs_hook=_unique)
    except (json.JSONDecodeError, ValueError) as exc:
        raise ValueError('invalid map JSON: '+str(exc)) from exc
    facts = validate_map(row['body'], mapping, GOAL_FIELDS if goal else FIELDS)
    row['format_version'] = 3
    row['_spans'] = mapping['spans']
    row['_prose'] = row['body']
    if not goal:
        row.pop('body')
        row.update(facts)
        row['refs'] = [x for x in re.split(r'[、,， ]+', row['refs']) if x]
    return row


def _unique(pairs):
    out = {}
    for k, v in pairs:
        if k in out:
            raise ValueError('duplicate JSON key: ' + k)
        out[k] = v
    return out


def serialize(row: dict, prose: str, quotes: dict | None = None, *, mapping=None, goal=False) -> str:
    if quotes is not None and mapping is not None:
        raise ValueError('supply quotes or spans, not both')
    mapping = mapping if mapping is not None else spans_for(prose, quotes or {}, GOAL_FIELDS if goal else FIELDS)
    validate_map(prose, mapping, GOAL_FIELDS if goal else FIELDS)
    if goal:
        head = f'- 【{row["status"]}】【{row["id"]}】【{row["object"]}】：'
    else:
        refs = row['refs'] if isinstance(row['refs'], str) else '、'.join(row['refs'])
        head = f'- 【{row["status"]}】【{row["id"]}】【对应 {refs}】【{row["object"]}】：'
    comment = (GOAL_PREFIX if goal else FACT_PREFIX)+canonical(mapping).decode()+' -->'
    parse_pair(head+prose, comment, goal=goal)
    return head+prose+'\n'+comment


def blocks(text: str, *, goal=False) -> tuple[list[dict], list[str]]:
    marker = GOAL_MARKER if goal else TEST_MARKER
    prefix = GOAL_PREFIX if goal else FACT_PREFIX
    lines = [s.strip() for s in text.splitlines() if s.strip() and not s.strip().startswith('<!-- APCF-META ')]
    if lines and lines[0].startswith('# '):
        lines.pop(0)
    errors = []
    if not lines or lines[0] != marker or lines.count(marker) != 1:
        errors.append('new narrative document must have exactly one marker following its heading')
    if lines and lines[0] == marker:
        lines.pop(0)
    rows = []
    for i in range(0, len(lines), 2):
        try:
            if i+1 >= len(lines):
                raise ValueError('orphan narrative line')
            rows.append(parse_pair(lines[i], lines[i+1], goal=goal))
        except ValueError as exc:
            errors.append(f'record {i//2+1}: {exc}')
    return rows, errors
