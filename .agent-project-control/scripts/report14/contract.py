# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HOME = Path(__file__).resolve().parents[2] / 'reporting'
CONTRACT = json.loads((HOME / 'contract.json').read_text(encoding='utf-8'))
SECTIONS = {s['number']: s for s in CONTRACT['sections']}
MAX_BYTES = 2_000_000
MAX_RECORDS = 1000
EMPTY = ('本轮无相关事项', '本轮不适用', '当前尚无足够记录确认本区内容', '无', '不适用')

def sha(data: str | bytes) -> str:
    return hashlib.sha256(data.encode('utf-8') if isinstance(data, str) else data).hexdigest()

def normalize(text: str) -> str:
    return text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')

def verify_authority() -> bool:
    return sha((HOME / CONTRACT['reference_file']).read_bytes()) == CONTRACT['reference_sha256']

def guidance(section: int, field: str | None = None) -> dict:
    index = json.loads((HOME / 'repair-index.json').read_text(encoding='utf-8'))
    if not verify_authority() or index['reference_sha256'] != CONTRACT['reference_sha256']:
        raise ValueError('authority mismatch')
    item = index['sections'][str(section)]
    rows = item['constraints']
    chosen = [r for r in rows if r['field'] == '__section__' or (field and r['field'] in (field, '失败原因／阻塞原因' if field in ('失败原因','阻塞原因') else field))]
    if not chosen:
        chosen = rows
    examples = item['examples']
    # One case only: do not send a complete unrelated tutorial to a local repair.
    import re
    matches = list(re.finditer(r'^\*\*【', examples, re.M))
    if matches:
        cases=[examples[m.start():matches[i+1].start() if i+1<len(matches) else len(examples)] for i,m in enumerate(matches)]
        examples=next((c for c in cases if field and re.search(r'^- '+re.escape(field)+'：',c,re.M)),cases[0])
    if field:
        m = re.search(r'^- ' + re.escape(field) + r'：[\s\S]*?(?=\n- |\Z)', examples, re.M)
        if m:
            examples = m[0]
    return {'section': section, 'title': item['title'], 'constraints': chosen,
            'example': examples[:5000], 'source_sha256': index['reference_sha256']}
