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
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--check',action='store_true'); ap.add_argument('--update-lock',action='store_true'); a=ap.parse_args(); ok=True
    if a.check and a.update_lock: ap.error('--check and --update-lock cannot be combined')
    lock=FRAMEWORK_ROOT/'skills/SKILLS.lock.yaml'; text=lock.read_text(encoding='utf-8'); cache=(ROOT/'.codex/skills').resolve()
    for s in parse():
        if not re.fullmatch(r'[A-Za-z0-9_-]+',s['id']) or not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',s['source']): raise SystemExit('FAIL: invalid skill id or source')
        required=s.get('required',True)
        d=cache/s['id']
        if d.is_symlink() or d.resolve().parent!=cache: raise SystemExit('FAIL: skill destination escapes cache')
        if s.get('mode') not in (None, 'pinned-local'):
            raise SystemExit('FAIL: unsupported skill install mode for '+s['id'])
        expected_sha = s.get('skill_sha256')
        if s.get('mode') == 'pinned-local' and not expected_sha:
            raise SystemExit('FAIL: pinned-local skill missing skill_file_sha256 for '+s['id'])
        if expected_sha and not re.fullmatch(r'[0-9a-f]{64}',expected_sha):
            raise SystemExit('FAIL: invalid skill_file_sha256 for '+s['id'])
        skill_file=d/'SKILL.md'
        good=skill_file.is_file()
        if good and expected_sha:
            good=hashlib.sha256(skill_file.read_bytes()).hexdigest()==expected_sha
        if good and s.get('mode')!='pinned-local' and s.get('commit','null')!='null':
            r=subprocess.run(['git','-C',str(d),'rev-parse','HEAD'],capture_output=True,text=True)
            good=r.returncode==0 and r.stdout.strip()==s['commit']
        if not d.exists() and not required and (a.check or s.get('mode')=='pinned-local'):
            print('OPTIONAL_UNAVAILABLE: '+s['id'])
            continue
        if a.check or s.get('mode')=='pinned-local':
            print(('PASS' if good else 'MISSING OR MISMATCH')+': '+s['id']
                  + (' (pinned-local, not overwritten)' if s.get('mode')=='pinned-local' else ''))
            ok &= good
        else:
            if d.exists(): shutil.rmtree(d,onerror=remove_readonly)
            subprocess.run(['git','clone','--depth','1','--branch',s.get('ref','main'),f"https://github.com/{s['source']}.git",str(d)],check=True)
            if s.get('commit','null')!='null' and not a.update_lock:
                subprocess.run(['git','-C',str(d),'fetch','--depth','1','origin',s['commit']],check=True)
                subprocess.run(['git','-C',str(d),'checkout','--detach',s['commit']],check=True)
            commit=subprocess.check_output(['git','-C',str(d),'rev-parse','HEAD'],text=True).strip()
            if s.get('commit','null')!='null' and not a.update_lock and commit!=s['commit']:
                raise SystemExit('FAIL: resolved commit mismatch for '+s['id'])
            if expected_sha:
                if not skill_file.is_file(): raise SystemExit('FAIL: downloaded skill file missing for '+s['id'])
                actual_sha=hashlib.sha256(skill_file.read_bytes()).hexdigest()
                if actual_sha!=expected_sha: raise SystemExit('FAIL: downloaded skill file hash mismatch for '+s['id'])
            pattern=r'(?ms)(^  - id: '+re.escape(s['id'])+r'\n(?:(?!^  - id: ).)*?    resolved_commit: )[^\n]+'
            text,count=re.subn(pattern,lambda m:m.group(1)+commit,text,count=1)
            if count!=1: raise SystemExit('FAIL: resolved_commit missing for '+s['id'])
            lock.write_text(text,encoding='utf-8'); print('PASS: '+s['id']+' @ '+commit)
    if not ok: raise SystemExit(2)
if __name__=='__main__': main()
