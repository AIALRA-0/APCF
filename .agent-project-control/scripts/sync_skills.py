# APCF-META {"schema":1,"visibility":"public"}
import argparse,subprocess,shutil,re,stat,hashlib
from common import ROOT,FRAMEWORK_ROOT
def parse():
    out=[]; cur=None
    for line in (FRAMEWORK_ROOT/'skills/SKILLS.lock.yaml').read_text(encoding='utf-8').splitlines():
        s=line.strip()
        if s.startswith('- id:'):
            if cur: out.append(cur)
            cur={'id':s.split(':',1)[1].strip()}
        elif cur and s.startswith('source:'): cur['source']=s.split(':',1)[1].strip()
        elif cur and s.startswith('requested_ref:'): cur['ref']=s.split(':',1)[1].strip()
        elif cur and s.startswith('resolved_commit:'): cur['commit']=s.split(':',1)[1].strip()
        elif cur and s.startswith('install_mode:'): cur['mode']=s.split(':',1)[1].strip()
        elif cur and s.startswith('skill_file_sha256:'): cur['skill_sha256']=s.split(':',1)[1].strip()
        elif cur and s.startswith('required:'):
            value=s.split(':',1)[1].strip().lower()
            if value not in ('true','false'): raise SystemExit('FAIL: invalid required value for '+cur['id'])
            cur['required']=value=='true'
    if cur: out.append(cur)
    return out
def remove_readonly(func,path,exc):
    if not isinstance(exc[1],PermissionError): raise exc[1]
    from pathlib import Path
    Path(path).chmod(stat.S_IWRITE|stat.S_IREAD); func(path)

def _tree_safe(path):
    from repair_io import linked
    if linked(path): raise ValueError('skill path is a symlink/reparse point')
    for p in path.rglob('*'):
        if linked(p):raise ValueError('skill tree contains a symlink/reparse point')


def _verify_skill(folder, spec, *, pinned=True):
    _tree_safe(folder)
    file=folder/'SKILL.md'
    if not file.is_file():raise ValueError('SKILL.md missing')
    if spec.get('skill_sha256') and hashlib.sha256(file.read_bytes()).hexdigest()!=spec['skill_sha256']:
        raise ValueError('SKILL.md SHA differs from approved lock')
    commit=spec.get('commit','null')
    if spec.get('mode')!='pinned-local':
        value=subprocess.check_output(['git','-C',str(folder),'rev-parse','HEAD'],text=True).strip()
        if pinned and commit!='null' and value!=commit:raise ValueError('commit mismatch')
        dirty=subprocess.check_output(['git','-C',str(folder),'status','--porcelain','--untracked-files=all'],text=True)
        if dirty.strip():raise ValueError('local changes in skill; never overwrite them')
        return value
    return None


def synchronize_one(spec, cache, lock_path, *, update_lock=False):
    """Transaction per skill. Failure leaves the previous skill and lock unchanged."""
    import tempfile,os,uuid
    from pathlib import Path
    from repair_io import atomic,linked,lock as operation_lock
    folder=cache/spec['id']
    if linked(cache) or linked(folder):raise ValueError('unsafe skill cache')
    with operation_lock(FRAMEWORK_ROOT/'runtime/tmp/.skills.lock'):
        before=lock_path.read_bytes()
        if folder.exists():
            _verify_skill(folder,spec)  # refuses user-modified or unidentified existing data
            if not update_lock:return 'UNCHANGED'
        if spec.get('mode')=='pinned-local':
            raise ValueError('pinned-local snapshot unavailable; no guessed remote fallback')
        stage=Path(tempfile.mkdtemp(prefix='.skill-stage-',dir=cache))
        clone=stage/'candidate';backup=cache/('.skill-backup-'+uuid.uuid4().hex)
        moved=False;installed=False;committed=False
        def fingerprint(path):
            _tree_safe(path)
            return {p.relative_to(path).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in path.rglob("*") if p.is_file()}
        old_tree=fingerprint(folder) if folder.is_dir() else None
        try:
            subprocess.run(['git','clone','--no-checkout',f"https://github.com/{spec['source']}.git",str(clone)],check=True)
            ref=spec.get('ref','main') if update_lock or spec.get('commit','null')=='null' else spec['commit']
            subprocess.run(['git','-C',str(clone),'checkout','--detach',ref],check=True)
            commit=_verify_skill(clone,spec,pinned=not update_lock)
            if (fingerprint(folder) if folder.is_dir() else None)!=old_tree:raise ValueError("existing skill changed while download was in progress")
            if lock_path.read_bytes()!=before:raise ValueError("skill lock changed before commit")
            if folder.exists():folder.rename(backup);moved=True
            clone.rename(folder);installed=True
            if update_lock or spec.get('commit','null')=='null':
                text=before.decode('utf-8')
                pattern=r'(?ms)(^  - id: '+re.escape(spec['id'])+r'\r?\n(?:(?!^  - id: ).)*?    resolved_commit: )[^\r\n]+'
                text,n=re.subn(pattern,lambda m:m.group(1)+commit,text,count=1)
                if n!=1:raise ValueError('lock entry not unique')
                atomic(lock_path,text.encode('utf-8'),expected=before,compare=True)
            committed=True
            if moved:
                try:shutil.rmtree(backup,onerror=remove_readonly)
                except OSError:print('NOTE: committed skill is valid; original backup retained for manual recovery: '+str(backup))
            return 'INSTALLED'
        except BaseException:
            if committed:raise  # postcommit cleanup cannot roll back only half of a valid upgrade
            if installed and folder.exists():shutil.rmtree(folder,onerror=remove_readonly)
            if moved and backup.exists():backup.rename(folder)
            # If a concurrent actor changed the lock, do not overwrite that actor's bytes.
            if lock_path.read_bytes()!=before:
                raise RuntimeError('skill failed and lock changed externally; original skill restored, inspect lock')
            raise
        finally:
            if stage.exists():shutil.rmtree(stage,onerror=remove_readonly)


def main():
    from pathlib import Path
    ap=argparse.ArgumentParser();ap.add_argument('--check',action='store_true');ap.add_argument('--update-lock',action='store_true')
    a=ap.parse_args()
    if a.check and a.update_lock:ap.error('--check and --update-lock cannot be combined')
    cache=ROOT/'.codex/skills';lock_path=FRAMEWORK_ROOT/'skills/SKILLS.lock.yaml'
    if not a.check:cache.mkdir(parents=True,exist_ok=True)
    failed=False
    for spec in parse():
        if not re.fullmatch(r'[A-Za-z0-9_-]+',spec['id']) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',spec['source']):
            raise SystemExit('FAIL: unsafe skill ID/source')
        folder=cache/spec['id']
        if not folder.exists() and not spec.get('required',True) and (a.check or spec.get('mode')=='pinned-local'):
            print('OPTIONAL_UNAVAILABLE: '+spec['id']);continue
        try:
            if a.check:_verify_skill(folder,spec);result='PRESENT'
            else:result=synchronize_one(spec,cache,lock_path,update_lock=a.update_lock)
            print(result+': '+spec['id'])
        except Exception as exc:
            print('BLOCKED: '+spec['id']+': '+str(exc));failed=True
    if failed:raise SystemExit(2)
if __name__=='__main__':main()
