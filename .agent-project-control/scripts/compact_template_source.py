# APCF-META {"schema":1,"visibility":"public"}
import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from common import ROOT, FRAMEWORK_ROOT


def git(*args):
    return subprocess.check_output(["git",*args],cwd=ROOT,text=True,encoding="utf-8").strip()


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--apply",action="store_true")
    ap.add_argument("--archive-ref",default=None)
    a=ap.parse_args()
    if "template_source: true" not in (FRAMEWORK_ROOT/"framework.yaml").read_text(encoding="utf-8"):
        raise SystemExit("FAIL: compaction is allowed only in the template source repository")
    current=(ROOT/"CURRENT.md").read_text(encoding="utf-8")
    match=re.search(r"Source TURN[^`]*`([^`]+)`",current)
    if not match: raise SystemExit("FAIL: CURRENT has no Source TURN; finalize a current turn first")
    keep=(ROOT/match.group(1)).resolve()
    iterations=(FRAMEWORK_ROOT/"iterations").resolve()
    if not keep.is_relative_to(iterations) or not (keep/"TURN.md").is_file():
        raise SystemExit("FAIL: CURRENT points to an invalid turn")
    keep_it=keep.parents[1]
    reference_files=[ROOT/"CURRENT.md",keep_it/"ITERATION.md",*[keep/name for name in ("TURN.md","CHECKLIST.md","TEST.md")],* (FRAMEWORK_ROOT/"rules").glob("*.md"),* (FRAMEWORK_ROOT/"regressions").rglob("*.md")]
    references="\n".join(p.read_text(encoding="utf-8") for p in reference_files)
    targets=[]
    for it in iterations.glob("IT-*"):
        if it.resolve()!=keep_it:
            if it.name not in references: targets.append(it)
        else:
            targets.extend(tr for tr in (it/"turns").glob("TR-*") if tr.resolve()!=keep and tr.name not in references)
    for mat in (FRAMEWORK_ROOT/"materials").glob("MAT-*"):
        if mat.name not in references: targets.append(mat)
    historical=list(targets)
    runtime=(FRAMEWORK_ROOT/"runtime").resolve()
    for p in runtime.iterdir():
        if p.name==".apcf-dir.yaml": continue
        if p.is_dir(): targets.extend(q for q in p.iterdir() if q.name!=".apcf-dir.yaml")
        else: targets.append(p)
    # Verify every resolved deletion target before any mutation, including junction escapes
    for p in targets:
        resolved=p.resolve()
        if p.is_symlink() or not resolved.is_relative_to(FRAMEWORK_ROOT.resolve()) or resolved==FRAMEWORK_ROOT.resolve():
            raise SystemExit("FAIL: unsafe deletion target: "+str(p))
        for child in p.rglob("*") if p.is_dir() else []:
            if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                raise SystemExit("FAIL: escaped deletion child: "+str(child))
    print("KEEP:",keep.relative_to(ROOT))
    for p in targets: print(("DELETE " if a.apply else "DRY-RUN ")+str(p.relative_to(ROOT)))
    if not a.apply:
        print("PASS: preview only; apply requires matching Git recovery objects")
        return
    # Prove old operational files are recoverable before clearing the source tree
    refs=["HEAD"]+([a.archive_ref] if a.archive_ref else [])
    for p in historical:
        for f in p.rglob("*") if p.is_dir() else [p]:
            if not f.is_file(): continue
            rel=f.relative_to(ROOT).as_posix()
            blob=git("hash-object","--path="+rel,str(f))
            saved=False
            for ref in refs:
                result=subprocess.run(["git","rev-parse",ref+":"+rel],cwd=ROOT,capture_output=True,text=True)
                if result.returncode==0 and result.stdout.strip()==blob: saved=True; break
            if not saved: raise SystemExit("FAIL: history not preserved in Git: "+rel)
    for p in sorted(set(targets),key=lambda p:len(p.parts),reverse=True):
        if p.exists(): shutil.rmtree(p) if p.is_dir() else p.unlink()
    for script in ["refresh_indexes.py","render_tree.py","state_integrity.py"]:
        subprocess.run([sys.executable,"-B",str(FRAMEWORK_ROOT/"scripts"/script)],cwd=ROOT,check=True)
    print("PASS: template-source history compacted; current Source TURN preserved and older files recoverable from Git")


if __name__=="__main__": main()
