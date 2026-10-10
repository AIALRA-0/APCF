# APCF-META {"schema":1,"visibility":"public"}
#!/usr/bin/env python3
"""Read-only GitHub release verification; no branch/tag/notes/asset modification.

Checks a named public repo/ref and anonymously downloads exact assets into a NEW
external directory. Local manifest pin must come from the reviewed candidate,
not the same untrusted remote download. Ordinary Git refs are read separately.
"""
from __future__ import annotations
import argparse,hashlib,json,re,subprocess,sys
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.parse import urlparse
import release_candidate as R

REPO='AIALRA-0/APCF'

def public_json(path):
    req=Request('https://api.github.com/repos/'+REPO+'/'+path,headers={'Accept':'application/vnd.github+json','User-Agent':'APCF-release-readback'})
    with urlopen(req,timeout=45) as r:return json.load(r)

def refs(text,expected_main,tag,allowed=()):
    rows={}
    known={'HEAD','refs/heads/main',*[f'refs/tags/{t}{suffix}' for t in (tag,'v0.3.0-closeout-v2') for suffix in ('','^{}')]}
    for ref in allowed:
        if not re.fullmatch(r'refs/(?:heads|tags)/[A-Za-z0-9_./-]+(?:\^\{\})?',ref) or '..' in ref:raise ValueError('invalid explicitly reviewed ref')
        known.add(ref)
    for line in text.splitlines():
        fields=line.split()
        if len(fields)!=2 or not re.fullmatch(r'[0-9a-f]{40,64}',fields[0]):raise ValueError('malformed remote ref response')
        oid,ref=fields
        if ref in rows:raise ValueError('duplicated advertised reference')
        if ref not in known:raise ValueError('unexpected remote reference; independent review/authorization required: '+ref)
        rows[ref]=oid
    if rows.get('refs/heads/main')!=expected_main:raise ValueError('main differs from reviewed commit')
    target=rows.get('refs/tags/'+tag+'^{}',rows.get('refs/tags/'+tag))
    if target!=expected_main:raise ValueError('tag does not resolve to reviewed commit')
    return rows

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--commit',required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--download-dir',required=True);p.add_argument('--git',default='git');p.add_argument('--allow-ref',action='append',default=[])
    a=p.parse_args()
    try:
        if not re.fullmatch(r'[0-9a-f]{40,64}',a.commit) or not re.fullmatch(r'[0-9a-f]{64}',a.manifest_sha256):raise ValueError('explicit pinned commit and reviewed manifest SHA required')
        out=R.ordinary(a.download_dir)
        if out.exists() or not out.parent.is_dir():raise ValueError('download directory must be new')
        metadata=public_json('')
        if metadata.get('full_name')!=REPO or metadata.get('private') is not False:raise ValueError('repo is not the authorized PUBLIC target')
        rel=public_json('releases/tags/'+R.VERSION)
        if rel.get('draft') or rel.get('prerelease') or rel.get('tag_name')!=R.VERSION:raise ValueError('release is missing, draft, prerelease or wrong version')
        assets={x['name']:x for x in rel['assets']}
        names={f'APCF-Deploy-{R.VERSION}.zip',f'APCF-Deploy-{R.VERSION}.zip.sha256','RELEASE-MANIFEST.json'}
        if len(assets)!=len(rel['assets']) or set(assets)!=names:raise ValueError('release assets differ from reviewed set')
        remote=subprocess.run([a.git,'ls-remote','https://github.com/'+REPO+'.git'],capture_output=True,text=True,encoding='utf-8',timeout=60,check=True)
        actual_refs=refs(remote.stdout,a.commit,R.VERSION,a.allow_ref)
        checks=public_json('commits/'+a.commit+'/check-runs?per_page=100')
        suites=checks.get('check_runs',[])
        # Select the latest attempt by job name. Ignore old failed attempts, never a running latest attempt.
        latest={}
        for v in suites:
            name=v['name']
            if name not in latest or v['id']>latest[name]['id']:latest[name]=v
        required={'APCF Core / ubuntu-latest','APCF Core / windows-latest'}
        if not required<=set(latest) or any(latest[n].get('app',{}).get('slug')!='github-actions' or latest[n].get('head_sha')!=a.commit or latest[n].get('status')!='completed' or latest[n].get('conclusion')!='success' for n in required):
            raise ValueError('required current Linux/Windows CI checks not successful for reviewed commit')
        out.mkdir(mode=0o700)
        for name in sorted(names):
            url=assets[name]['browser_download_url'];u=urlparse(url)
            if u.scheme!='https' or u.hostname!='github.com' or not u.path.startswith('/'+REPO+'/releases/download/'+R.VERSION+'/'):
                raise ValueError('unexpected asset endpoint')
            with urlopen(Request(url,headers={'User-Agent':'APCF-release-readback'}),timeout=60) as stream:
                data=stream.read(16*1024*1024+1)
            if len(data)>16*1024*1024 or len(data)!=assets[name]['size']:raise ValueError('asset length invalid')
            (out/name).write_bytes(data)
        if R.digest((out/'RELEASE-MANIFEST.json').read_bytes())!=a.manifest_sha256:raise ValueError('downloaded manifest differs from independently pinned candidate')
        result=R.verify(out)
        result.update(repo=REPO,commit=a.commit,release_id=rel['id'],refs=actual_refs,
                      anonymous_https=True,checked_ci={n:latest[n]['id'] for n in required},
                      status='PUBLIC_ASSETS_AND_REFERENCES_VERIFIED')
        (out/'REMOTE-READBACK.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,RuntimeError,KeyError,subprocess.SubprocessError) as e:
        print('BLOCKED:',e,file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
