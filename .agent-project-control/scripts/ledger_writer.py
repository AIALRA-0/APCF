# APCF-META {"schema":1,"visibility":"public"}
"""Render a supplied natural-narrative ledger without inventing findings or PASS states."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from test_ledger import serialize_v3,serialize_goal,TEST_NARRATIVE_MARKER,GOAL_NARRATIVE_MARKER,validate_text
from repair_io import exclusive


def render(rows,kind):
    if not isinstance(rows,list) or not rows:raise ValueError('a nonempty list of authored records is required')
    serializer=serialize_v3 if kind=='test' else serialize_goal
    marker=TEST_NARRATIVE_MARKER if kind=='test' else GOAL_NARRATIVE_MARKER
    title='当前验收记录' if kind=='test' else '当前执行目标'
    parts=['<!-- APCF-META {"schema":1,"visibility":"public"} -->','# 1. '+title,'',marker,'']
    for r in rows:
        if set(r)-{'status','id','refs','object','prose','quotes','mapping'}:raise ValueError('unknown authoring input field')
        parts += [serializer(r,r['prose'],r.get('quotes'),mapping=r.get('mapping')),'']
    return '\n'.join(parts)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('kind',choices=['test','goal']);p.add_argument('--input',required=True);p.add_argument('--output',required=True)
    a=p.parse_args()
    try:
        result=render(json.loads(Path(a.input).read_text(encoding='utf-8')),a.kind)
        exclusive(Path(a.output),result.encode())
        print('CREATED: authored text with bound offsets; no business check was executed')
    except (ValueError,KeyError,OSError) as e:print('BLOCKED:',e);return 2
    return 0
if __name__=='__main__':raise SystemExit(main())
