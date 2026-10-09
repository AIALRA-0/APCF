# APCF-META {"schema":1,"visibility":"public"}
import hashlib
import json
import os
import re
from pathlib import Path
from common import ROOT,FRAMEWORK_ROOT,parse_meta
from rule_sync import MODULES,RULE_HEADING,sync as sync_rules
from design_contract import validate as validate_design
from standards_contract import validate as validate_standards

RUNTIME_SCAFFOLD=('testbed','runs','downloads','tmp','cache','large','distribution')
MANAGED_TEXT_SUFFIXES={'.md','.yaml','.py','.html'}
FROZEN_HASH_SCOPE='sha256-tree-v1-excluding-apcf-dir-yaml'
FROZEN_MARKER_KEYS={'schema','visibility','kind','path','sha256','freeze_id','hash_scope'}
FROZEN_MARKER_TRIGGER_KEYS={'kind','path','sha256','freeze_id','hash_scope'}

def _walk_framework_without_runtime(framework_root=FRAMEWORK_ROOT):
    """Walk managed framework content while pruning runtime at its root."""
    framework_root=Path(framework_root)
    for current,dirs,files in os.walk(framework_root,topdown=True,followlinks=False):
        current_path=Path(current)
        if current_path==framework_root:
            dirs[:]=[name for name in dirs if name!='runtime']
        dirs[:]=[name for name in dirs if name!='__pycache__']
        yield current_path,dirs,files

def managed_text_files(framework_root=FRAMEWORK_ROOT):
    """Return managed text files outside the runtime temporary-content tree."""
    files=[]
    for current,_,names in _walk_framework_without_runtime(framework_root):
        files.extend(current/name for name in names
                     if name!='.apcf-dir.yaml' and Path(name).suffix.lower() in MANAGED_TEXT_SUFFIXES)
    return sorted(files)

def managed_directories(framework_root=FRAMEWORK_ROOT):
    """Return normal managed directories without walking runtime descendants."""
    return [current for current,_,_ in _walk_framework_without_runtime(framework_root)]

def metadata_errors(files,root=ROOT):
    """Report managed text files without an embedded header or metadata sidecar."""
    root=Path(root)
    errors=[]
    for path in files:
        path=Path(path)
        if path.name=='.apcf-dir.yaml' or not path.exists():
            continue
        if not (parse_meta(path) or parse_meta(path.with_name(path.name+'.apcf-meta.yaml'))):
            errors.append('metadata missing: '+str(path.relative_to(root)))
    return errors

def runtime_boundary_errors(framework_root=FRAMEWORK_ROOT):
    """Require private, non-symlink markers at runtime and its seven scaffold roots."""
    framework_root=Path(framework_root)
    runtime=framework_root/'runtime'
    errors=[]
    if runtime.is_symlink() or not runtime.is_dir():
        return ['missing or unsafe runtime root: '+str(runtime)]
    for directory in [runtime,*(runtime/name for name in RUNTIME_SCAFFOLD)]:
        marker=directory/'.apcf-dir.yaml'
        if directory.is_symlink() or not directory.is_dir():
            errors.append('missing or unsafe runtime scaffold: '+str(directory))
            continue
        if marker.is_symlink() or not marker.is_file():
            errors.append('runtime scaffold marker missing: '+str(marker))
            continue
        try:
            lines=marker.read_text(encoding='utf-8').splitlines()
        except (OSError,UnicodeError):
            errors.append('runtime scaffold marker unreadable: '+str(marker))
            continue
        meta=parse_meta(marker)
        if (not isinstance(meta,dict) or type(meta.get('schema')) is not int or meta.get('schema')!=1 or
                meta.get('visibility')!='private' or set(meta)!={'schema','visibility'} or
                lines[1:]!=['schema: 1','visibility: private']):
            errors.append('runtime scaffold marker must declare only schema 1 and private visibility: '+str(marker))
    return errors

def directory_tree_sha256(directory):
    """Hash a frozen directory tree while excluding directory metadata markers."""
    directory=Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('unsafe frozen directory: '+str(directory))
    digest=hashlib.sha256()
    entries=sorted(directory.rglob('*'),key=lambda item:item.relative_to(directory).as_posix())
    for entry in entries:
        if entry.is_symlink():
            raise ValueError('symlink in frozen directory: '+str(entry))
        if entry.name=='.apcf-dir.yaml': continue
        relative=entry.relative_to(directory).as_posix().encode('utf-8')
        if entry.is_dir(): digest.update(b'D\0'+relative+b'\0')
        elif entry.is_file():
            file_digest=hashlib.sha256()
            with entry.open('rb') as stream:
                for block in iter(lambda:stream.read(1024*1024),b''): file_digest.update(block)
            digest.update(b'F\0'+relative+b'\0'+file_digest.digest())
    return digest.hexdigest()

def validate_frozen_directory_markers(directories,root=ROOT):
    """Validate only directory markers that declare a frozen content identity."""
    root=Path(root).resolve()
    errors=[]
    freeze_tokens=('freeze_id','hash_scope','sha256','kind','path')
    for directory in directories:
        directory=Path(directory)
        marker=directory/'.apcf-dir.yaml'
        if marker.is_symlink():
            try: raw=marker.read_bytes()
            except OSError: raw=b''
            if any(token.encode('ascii') in raw for token in freeze_tokens):
                errors.append('frozen directory marker is a symlink: '+str(marker))
            continue
        if not marker.is_file(): continue
        try:
            raw=marker.read_bytes()
            lines=raw.decode('utf-8').splitlines()
        except (OSError,UnicodeError):
            try: raw=marker.read_bytes()
            except OSError: raw=b''
            if any(token.encode('ascii') in raw for token in freeze_tokens):
                errors.append('frozen directory marker unreadable: '+str(marker))
            continue
        meta=parse_meta(marker)
        declares_frozen=(isinstance(meta,dict) and bool(FROZEN_MARKER_TRIGGER_KEYS.intersection(meta))) or any(
            token in raw.decode('utf-8','replace') for token in freeze_tokens
        )
        if not declares_frozen: continue
        try:
            expected_path=directory.resolve().relative_to(root).as_posix()
        except ValueError:
            errors.append('frozen directory escapes metadata root: '+str(directory))
            continue
        if directory.is_symlink() or not directory.is_dir():
            errors.append('frozen directory missing or unsafe: '+expected_path)
            continue
        if not isinstance(meta,dict) or set(meta)!=FROZEN_MARKER_KEYS:
            errors.append('frozen directory marker identity fields invalid: '+expected_path)
            continue
        if (type(meta.get('schema')) is not int or meta.get('schema')!=1 or
                meta.get('visibility')!='private' or meta.get('kind')!='directory' or
                meta.get('path')!=expected_path or not isinstance(meta.get('freeze_id'),str) or
                not meta['freeze_id'].strip() or meta.get('hash_scope')!=FROZEN_HASH_SCOPE or
                lines[1:]!=['schema: 1','visibility: private']):
            errors.append('frozen directory marker identity mismatch: '+expected_path)
            continue
        claimed=meta.get('sha256')
        if not isinstance(claimed,str) or not re.fullmatch(r'[0-9a-f]{64}',claimed):
            errors.append('frozen directory marker SHA format invalid: '+expected_path)
            continue
        try: actual=directory_tree_sha256(directory)
        except (OSError,ValueError) as ex:
            errors.append(str(ex))
            continue
        if claimed!=actual:
            errors.append('frozen directory SHA drift: '+expected_path)
    return errors

def main():
    e=[]
    req=['AGENTS.md','.agent-project-control/framework.yaml','.agent-project-control/interfaces/WRITING_STANDARD.md','.agent-project-control/rules/INDEX.md','.agent-project-control/rules/COVERAGE.md','.agent-project-control/skills/SKILLS.lock.yaml','.agent-project-control/design/INDEX.md','.agent-project-control/design/RULES.md','.agent-project-control/design/BASELINES.lock.yaml','.agent-project-control/design/VERIFICATION.md','.agent-project-control/design/PROVENANCE.md']+MODULES
    [e.append('missing: '+x) for x in req if not (ROOT/x).exists()]
    ag=(ROOT/'AGENTS.md').read_text(encoding='utf-8') if (ROOT/'AGENTS.md').exists() else ''
    if '"kind":' in ag: e.append('AGENTS metadata contains kind')
    if re.search(r'\bF\d{2}\b',ag): e.append('legacy Fxx rule id found')
    e.extend('design: '+x for x in validate_design())
    e.extend('standards: '+x for x in validate_standards())
    try:
        rows,expected_index,expected_agents=sync_rules(False)
        actual_index=(ROOT/'.agent-project-control/rules/INDEX.md').read_text(encoding='utf-8')
        if actual_index!=expected_index: e.append('rules/INDEX.md drifted from canonical module headings; run rule_sync.py')
        if ag!=expected_agents: e.append('AGENTS rule indexes drifted from canonical module headings; run rule_sync.py')
    except Exception as ex:
        rows=[]; e.append('rule sync validation failed: '+str(ex))
    seen={}
    for rel in MODULES:
        p=ROOT/rel
        if not p.exists(): continue
        text=p.read_text(encoding='utf-8')
        # Every full rule must carry the four core sections and at least one bad/good example pair
        starts=list(RULE_HEADING.finditer(text))
        for i,m in enumerate(starts):
            end=starts[i+1].start() if i+1<len(starts) else len(text)
            block=text[m.start():end]
            rid=m.group(1)
            seen[rid]=seen.get(rid,0)+1
            for token in ('原则','触发','必须','例外'):
                if token not in block: e.append(f'{rid} missing full section: {token}')
            if '错误示例（Bad Example）' not in block: e.append(f'{rid} missing Bad Example')
            if '正确示例（Good Example）' not in block: e.append(f'{rid} missing Good Example')
    for i in range(1,32):
        rid=f'R{i:02d}'
        if seen.get(rid,0)!=1: e.append(rid+f' canonical body count={seen.get(rid,0)}')
    for rid in sorted(set(seen)-{f'R{i:02d}' for i in range(1,32)}):
        e.append('unknown canonical Rule ID: '+rid)
    managed=[ROOT/'CURRENT.md',ROOT/'AGENTS.md',ROOT/'README.md',ROOT/'README.en.md',ROOT/'TEMPLATE_SPEC.md',ROOT/'CODEX_PROMPT.md',ROOT/'CODEX_DEPLOY.md',ROOT/'PILOT_TEST_PLAN.md',ROOT/'VALIDATION.md',ROOT/'.gitignore']
    managed += managed_text_files()
    e.extend(metadata_errors(managed))
    e.extend(runtime_boundary_errors())
    dirs=managed_directories()+[ROOT/'.codex',ROOT/'.codex/skills']
    for d in dirs:
        if d.exists() and not (d/'.apcf-dir.yaml').exists(): e.append('dir marker missing: '+str(d.relative_to(ROOT)))
    e.extend(validate_frozen_directory_markers(dirs))
    if e:
        [print('FAIL:',x) for x in e]; raise SystemExit(2)
    print('PASS: framework lint passed; R01-R31 full bodies, examples, routing and derived indexes are consistent')
if __name__=='__main__': main()
