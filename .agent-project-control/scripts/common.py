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
    best=0; pat=re.compile(rf'^{re.escape(prefix)}-(\d+)')
    for root in roots:
        root=Path(root)
        if not root.exists(): continue
        for p in root.rglob(prefix+'-*'):
            m=pat.match(p.name)
            if m: best=max(best,int(m.group(1)))
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
