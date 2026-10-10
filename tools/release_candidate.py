# APCF-META {"schema":1,"visibility":"public"}
#!/usr/bin/env python3
"""Build and audit minimal release candidates; never changes Git or a remote.

Source must be a locally repaired APCF tree. Positive membership and existing
Core distribution remain authoritative. The scanner is a narrow deterministic
check, not a universal secret-detection or license-certification engine.
"""
from __future__ import annotations
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import unicodedata
import zipfile

VERSION='v0.3.2'
ROOT_REQUIRED={'AGENTS.md','CURRENT.md','APCF-START.md','.agent-project-control/framework.yaml',
               '.agent-project-control/interfaces/APCF_ONBOARDING.md',
               '.agent-project-control/interfaces/EXECUTION_SUPERVISION.md',
               '.agent-project-control/scripts/supervisor.py','.agent-project-control/core-members.json'}
RESERVED={'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}
BANNED={'.git','.git-ai','node_modules','__pycache__','.venv','venv','.pytest_cache','.idea'}
TEXT_EXT={'.md','.txt','.py','.json','.yaml','.yml','.toml','.html','.svg','.js','.css','.ps1','.sh'}
EMAIL=re.compile(rb'(?i)(?<![\w.+-])[A-Z0-9._%+-]+@([A-Z0-9.-]+\.[A-Z]{2,})(?![A-Z0-9.-])')
CREDENTIAL=re.compile(rb'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[psuo]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|(?i:api[_-]?key|client[_-]?secret|password)\s*[:=]\s*["\']?[A-Za-z0-9+/=_-]{24,}')
MACHINE=re.compile(rb'(?i)[A-Z]:[/\\](?:Users[/\\][^/\\\s]+|AIALRA Codex Workspace)[/\\]')

def digest(raw):return hashlib.sha256(raw).hexdigest()
def ordinary(path):
    path=Path(path).absolute()
    for p in (path,*path.parents):
        if p.is_symlink() or (p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400):raise ValueError('linked/reparse path refused')
    return path.resolve()

def safe_member(name):
    if not isinstance(name,str) or not name or name.startswith('/') or '\\' in name or any(c in '<>:"|?*' or ord(c)<32 for c in name):
        raise ValueError('unsafe archive name: '+repr(name))
    parts=name.rstrip('/').split('/')
    if any(p in ('','.','..') or p[-1:] in ('.',' ') or p.split('.')[0].upper() in RESERVED for p in parts):
        raise ValueError('unsafe archive segment: '+repr(name))
    return '/'.join(unicodedata.normalize('NFC',p).casefold() for p in parts)

def privacy(data,label):
    if CREDENTIAL.search(data) or MACHINE.search(data):raise ValueError('potential secret/private path: '+label)
    for match in EMAIL.finditer(data):
        domain=match.group(1).decode('ascii').lower().rstrip('.')
        allowed=domain in {'example.com','example.org','example.net','users.noreply.github.com'}
        allowed=allowed or any(domain==d or domain.endswith('.'+d) for d in ('invalid','test','example','localhost'))
        allowed=allowed or any(domain.endswith('.'+d) for d in ('example.com','example.org','example.net'))
        if not allowed:raise ValueError('email needs explicit source review: '+label)

def zip_payload(data,label='archive',depth=0):
    if depth>2:raise ValueError('nested depth exceeds audited limit')
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if sum(i.file_size for i in z.infolist())>80*1024*1024:raise ValueError('archive expansion exceeds audit budget')
        if z.testzip():raise ValueError('ZIP CRC mismatch')
        keys=set();files={};dirs=set()
        for info in z.infolist():
            # Windows ZipInfo normalizes filename; audit the original header too.
            safe_member(info.orig_filename)
            key=safe_member(info.filename);mode=stat.S_IFMT(info.external_attr>>16)
            if mode not in (0,stat.S_IFREG,stat.S_IFDIR):raise ValueError('non-regular archive entry')
            if key in keys:raise ValueError('duplicate/case-colliding member')
            keys.add(key)
            if info.is_dir():dirs.add(key);continue
            if info.file_size>32*1024*1024:raise ValueError('oversized file')
            payload=z.read(info);files[info.filename]=payload
            if Path(info.filename).suffix.lower() in TEXT_EXT:privacy(payload,label+'!'+info.filename)
            if info.filename.lower().endswith('.zip'):zip_payload(payload,label+'!'+info.filename,depth+1)
        folded={safe_member(k) for k in files}
        for key in folded:
            for i in range(1,len(key.split('/'))):
                if '/'.join(key.split('/')[:i]) in folded:raise ValueError('file/directory collision')
        if folded&dirs:raise ValueError('file/directory collision')
        return files

def inventory(root):
    rows=[];keys=set()
    for p in sorted(root.rglob('*')):
        ordinary(p)
        if not p.is_file():continue
        rel=p.relative_to(root).as_posix();key=safe_member(rel)
        if key in keys:raise ValueError('case/Unicode path collision')
        keys.add(key)
        if BANNED.intersection(Path(rel).parts):raise ValueError('history/dependency cache leaked: '+rel)
        raw=p.read_bytes()
        if p.suffix.lower() in TEXT_EXT:privacy(raw,rel)
        if p.suffix.lower()=='.zip':zip_payload(raw,rel)
        rows.append({'path':rel,'bytes':len(raw),'sha256':digest(raw)})
    return rows

def audit(root):
    root=ordinary(root);rows=inventory(root);paths={r['path'] for r in rows}
    if not ROOT_REQUIRED<=paths:raise ValueError('required deployed entry missing: '+str(ROOT_REQUIRED-paths))
    policy=json.loads((root/'.agent-project-control/core-members.json').read_text(encoding='utf-8'))
    if set(policy['files'])!=paths:raise ValueError('candidate does not match exact positive Core membership')
    if 'template_source: false' not in (root/'.agent-project-control/framework.yaml').read_text():raise ValueError('source facts not reset')
    for rel in paths:
        if rel.startswith(('apps/','.agent-project-control/design/components/')):raise ValueError('optional app in Core')
        if re.search(r'(?:^|/)(?:IT|TR|PA|REG|MAT|ADR|RB)-\d',rel):raise ValueError('source historical instance leaked')
        if rel.startswith('.agent-project-control/runtime/') and Path(rel).name!='.apcf-dir.yaml':raise ValueError('runtime payload leaked')
    return rows

def pack(root,target):
    rows=audit(root)
    with zipfile.ZipFile(target,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for row in rows:
            item=zipfile.ZipInfo(row['path'],date_time=(2026,10,9,0,0,0));item.create_system=3
            item.external_attr=0o100644<<16;item.compress_type=zipfile.ZIP_DEFLATED
            z.writestr(item,(root/row['path']).read_bytes(),compresslevel=9)
    result=zip_payload(target.read_bytes())
    for row in rows:
        if digest(result[row['path']])!=row['sha256']:raise ValueError('packed bytes mismatch')
    return rows

def build(source,out):
    source=ordinary(source);out=ordinary(out)
    if out.exists() or out.is_relative_to(source) or source.is_relative_to(out) or not out.parent.is_dir():
        raise ValueError('choose a NEW external output directory')
    out.mkdir()
    command=[sys.executable,'-B',str(source/'.agent-project-control/scripts/prepare_distribution.py'),'--profile','core','--output',str(out/'core')]
    subprocess.run(command,cwd=source,env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8'),check=True)
    asset=out/f'APCF-Deploy-{VERSION}.zip';rows=pack(out/'core',asset)
    manifest={'schema':1,'version':VERSION,'framework_schema':'0.3.0','stage':'CANDIDATE_NOT_PUBLISHED',
              'archive':{'name':asset.name,'bytes':asset.stat().st_size,'sha256':digest(asset.read_bytes())},'files':rows}
    (out/'RELEASE-MANIFEST.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (out/(asset.name+'.sha256')).write_text(manifest['archive']['sha256']+'  '+asset.name+'\n',encoding='ascii')
    return manifest

def verify(download):
    root=ordinary(download);obj=json.loads((root/'RELEASE-MANIFEST.json').read_text(encoding='utf-8'))
    if obj.get('schema')!=1 or obj.get('version')!=VERSION:raise ValueError('release version mismatch')
    # Both current-source builders use schema 1; their archive field names differ.
    keys=[key for key in ('archive','zip') if key in obj]
    if len(keys)!=1:raise ValueError('manifest must identify exactly one archive')
    archive=obj[keys[0]]
    if not isinstance(archive,dict) or set(archive)!={'name','bytes','sha256'}:raise ValueError('invalid archive identity')
    if type(archive['bytes']) is not int or archive['bytes']<=0 or not isinstance(archive['sha256'],str) or not re.fullmatch(r'[0-9a-f]{64}',archive['sha256']):raise ValueError('invalid archive size or digest')
    name=archive['name'];safe_member(name)
    if '/' in name:raise ValueError('asset must have basename only')
    asset=root/name;raw=asset.read_bytes()
    if len(raw)!=archive['bytes'] or digest(raw)!=archive['sha256']:raise ValueError('downloaded ZIP identity mismatch')
    check=(root/(name+'.sha256')).read_text().strip()
    if check!=digest(raw)+'  '+name:raise ValueError('SHA sidecar does not match actual archive')
    payload=zip_payload(raw);rows=obj['files']
    if len({r['path'] for r in rows})!=len(rows) or set(payload)!={r['path'] for r in rows}:raise ValueError('manifest member set mismatch')
    for row in rows:
        if len(payload[row['path']])!=row['bytes'] or digest(payload[row['path']])!=row['sha256']:raise ValueError('member content mismatch')
    return {'status':'ASSET_BYTES_VERIFIED','files':len(rows),'sha256':digest(raw),'authenticity':'same-channel checksums, not a trusted signature'}

def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='cmd',required=True)
    b=sub.add_parser('build');b.add_argument('--source',required=True);b.add_argument('--output',required=True)
    v=sub.add_parser('verify');v.add_argument('--download-dir',required=True)
    a=sub.add_parser('audit');a.add_argument('--core',required=True)
    o=p.parse_args()
    try:
        r=build(o.source,o.output) if o.cmd=='build' else verify(o.download_dir) if o.cmd=='verify' else {'files':audit(o.core)}
        print(json.dumps(r,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError,RuntimeError,subprocess.SubprocessError,zipfile.BadZipFile) as e:
        print('BLOCKED:',str(e),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
