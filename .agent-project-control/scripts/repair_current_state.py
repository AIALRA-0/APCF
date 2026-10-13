# APCF-META {"schema":1,"visibility":"public"}
import argparse
import re
import subprocess
from pathlib import Path
from common import ROOT, FRAMEWORK_ROOT, dir_marker, write_md
from state_integrity import validate

SOURCE_RE=re.compile(r"Source TURN[^`]*`([^`]+)`")
REPORT_MARKER="## 1.1. 最新完整用户报告"
IT_RE=re.compile(r"\*\*当前 IT\*\*：([^，\n]+)(?:，目标为 ([^，\n]+))?(?:，状态 ([A-Z]+))?")

def section(report,n,title):
    start=re.search(rf"^## {n}\. {re.escape(title)}\s*$",report,re.M)
    if not start: raise SystemExit(f"FAIL: report missing section {n}. {title}")
    nxt=re.search(rf"^## {n+1}\. ",report[start.end():],re.M) if n<9 else None
    end=start.end()+(nxt.start() if nxt else len(report[start.end():]))
    return report[start.end():end].strip()

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--stage",action="store_true")
    a=ap.parse_args()
    current=ROOT/"CURRENT.md"
    text=current.read_text(encoding="utf-8")
    sm=SOURCE_RE.search(text)
    if not sm: raise SystemExit("FAIL: CURRENT has no Source TURN")
    turn=(ROOT/sm.group(1)).resolve()
    from report14.bindings import report_text
    report=report_text(text).strip()
    iterations=(FRAMEWORK_ROOT/"iterations").resolve()
    if not turn.is_relative_to(iterations) or len(turn.relative_to(iterations).parts)!=3 or turn.parent.name!="turns":
        raise SystemExit("FAIL: Source TURN must be a canonical turn inside iterations")
    it=turn.parents[1]; turns=it/"turns"
    required=[it/'ITERATION.md', turn/'CHECKLIST.md', turn/'TEST.md', turn/'TURN.md']
    missing=[p.relative_to(ROOT).as_posix() for p in required if not p.is_file() or p.is_symlink()]
    if missing:
        raise SystemExit('BLOCKED: report text cannot reconstruct authoritative lifecycle state; restore verified originals: '+', '.join(missing))
    # No default COMPLETED, no invented FINALIZED, and no automatic private-to-public promotion.
    # REQUEST.md is never reconstructed from a report.
    from refresh_indexes import main as refresh
    refresh()
    errors=validate(False)
    if errors:
        for e in errors: print("FAIL:",e)
        raise SystemExit(2)
    if a.stage:
        paths=[
            current,
            it/".apcf-dir.yaml",it/"ITERATION.md",
            turns/".apcf-dir.yaml",
            turn/".apcf-dir.yaml",turn/"CHECKLIST.md",turn/"TEST.md",turn/"TURN.md",
            FRAMEWORK_ROOT/"iterations"/"INDEX.md",
        ]
        subprocess.run(["git","add","-f","--",*[str(p.relative_to(ROOT)) for p in paths if p.exists()]],cwd=ROOT,check=True)
        print("STAGED: durable current-state subset; REQUEST.md/private evidence were not invented or staged")
    print("PASS: current Source TURN durable subset exists")

if __name__=="__main__":
    main()
