# APCF-META {"schema":1,"visibility":"public"}
from pathlib import Path
import json,re
from datetime import datetime
ROOT=Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT=ROOT/".agent-project-control"
TEXT_META_RE=re.compile(r'^<!-- APCF-META\s+(\{.*?\})\s+-->$')
COMMENT_META_RE=re.compile(r'^# APCF-META\s+(\{.*?\})$')
def now_stamp(): return datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
def slugify(v):
    v=re.sub(r'[^A-Za-z0-9\u4e00-\u9fff]+','-',v.strip()); return v.strip('-')[:64] or 'untitled'
def meta_line(vis='public',comment=False):
    body=json.dumps({'schema':1,'visibility':vis},ensure_ascii=False,separators=(',',':')); return ('# APCF-META '+body) if comment else ('<!-- APCF-META '+body+' -->')
def dir_marker(p,vis='public'):
    p=Path(p); p.mkdir(parents=True,exist_ok=True); (p/'.apcf-dir.yaml').write_text(meta_line(vis,True)+f'\nschema: 1\nvisibility: {vis}\n',encoding='utf-8')
def write_md(p,body,vis='public'):
    p=Path(p); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(meta_line(vis)+'\n'+body.rstrip()+'\n',encoding='utf-8')
def next_id(prefix,*roots):
    from repair_io import lock, private_json
    registry=FRAMEWORK_ROOT/'runtime/runs/id-reservations.json'
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.ids.lock'):
        saved=json.loads(registry.read_text(encoding='utf-8')) if registry.exists() else {'schema':1,'max':{}}
        if saved.get('schema') != 1 or not isinstance(saved.get('max'),dict):
            raise ValueError('invalid ID reservation registry; do not reset numbering')
        best=int(saved['max'].get(prefix,0));pat=re.compile(rf'^{re.escape(prefix)}-(\d+)')
        for root in roots:
            root=Path(root)
            if root.exists():
                for p in root.rglob(prefix+'-*'):
                    m=pat.match(p.name)
                    if m:best=max(best,int(m.group(1)))
        saved['max'][prefix]=best+1
        private_json(registry,saved)
        return f'{prefix}-{best+1:04d}'

def parse_meta(p):
    try: first=Path(p).read_text(encoding='utf-8').splitlines()[0]
    except Exception: return None
    for rx in (TEXT_META_RE,COMMENT_META_RE):
        m=rx.match(first)
        if m:
            try:return json.loads(m.group(1))
            except Exception:return None
    return None
