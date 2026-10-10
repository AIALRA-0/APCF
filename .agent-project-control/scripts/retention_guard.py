# APCF-META {"schema":1,"visibility":"public"}
"""Conservative runtime retention inventory. No implicit blanket-delete authorization."""
from __future__ import annotations
import json
from pathlib import Path
import os
from repair_io import digest, inside, linked, canonical


def inventory(root: Path) -> dict:
    root=Path(root).resolve();runtime=root/'.agent-project-control/runtime'
    rows=[]
    if not runtime.is_dir():return {'schema':1,'objects':[],'read_only':True}
    # Every owned top-level runtime object is inventoried; no age-based inference of disposability.
    for scaffold in sorted(runtime.iterdir()):
        if scaffold.name=='.apcf-dir.yaml':continue
        targets=list(scaffold.iterdir()) if scaffold.is_dir() and not linked(scaffold) else [scaffold]
        for obj in sorted(targets):
            if obj.name=='.apcf-dir.yaml':continue
            rel=obj.relative_to(root).as_posix()
            row={'path':rel,'bytes':0,'files':0,'status':'RETAIN_UNCLASSIFIED','sha256':None,'references':[]}
            entries=[]
            if linked(obj):row['status']='BLOCKED_LINK'
            else:
                for p in sorted(obj.rglob('*')) if obj.is_dir() else [obj]:
                    if linked(p):row['status']='BLOCKED_LINK';break
                    if p.is_file():
                        data=p.read_bytes();row['bytes']+=len(data);row['files']+=1
                        entries.append([p.relative_to(root).as_posix(),len(data),digest(data)])
                row['sha256']=digest(canonical(entries))
            rows.append(row)
    # Unknown/unparseable references cause retention, not a guess that they are harmless.
    for folder,dirs,files in os.walk(root):
        here=Path(folder)
        dirs[:]=[d for d in dirs if d not in {'.git','node_modules','.venv','__pycache__'} and not linked(here/d)
                 and not (here/d).resolve().is_relative_to(runtime.resolve())]
        for name in files:
            p=here/name
            if linked(p) or p.suffix.lower() not in {'.md','.json','.jsonl','.txt','.yaml','.toml','.html'}:continue
            try:text=p.read_text(encoding='utf-8')
            except (OSError,UnicodeError):continue
            portable=text.replace('\\\\','/').replace('\\','/')
            for row in rows:
                rel=row['path'];absolute=(root/rel).as_posix()
                # Basename match is recall-first and deliberately conservative.
                if rel in portable or absolute in portable or Path(rel).name in portable:
                    row['references'].append(p.relative_to(root).as_posix());row['status']='RETAIN_REFERENCED'
    return {'schema':1,'read_only':True,'objects':rows,
            'limits':'Cannot establish references outside this workspace. Unknown ownership is retained.'}


def deny_blanket_cleanup():
    raise SystemExit('BLOCKED: blanket cleanup is not an authorized deletion plan. Keep referenced/unclassified objects; use reviewed retention inventory and an external recoverable archive.')
