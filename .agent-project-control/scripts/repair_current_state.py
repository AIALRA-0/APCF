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
    report=text.split(REPORT_MARKER,1)[1].strip()
    iterations=(FRAMEWORK_ROOT/"iterations").resolve()
    if not turn.is_relative_to(iterations) or len(turn.relative_to(iterations).parts)!=3 or turn.parent.name!="turns":
        raise SystemExit("FAIL: Source TURN must be a canonical turn inside iterations")
    it=turn.parents[1]; turns=it/"turns"
    dir_marker(it); dir_marker(turns); dir_marker(turn)
    for name in ["evidence","parallel"]:
        d=turn/name
        if not (d/".apcf-dir.yaml").exists(): dir_marker(d,"private")
    status="COMPLETED"; objective="Recovered current framework state"
    m=IT_RE.search(report)
    if m:
        objective=(m.group(2) or objective).strip()
        status=(m.group(3) or status).strip()
    if not (it/"ITERATION.md").exists():
        write_md(it/"ITERATION.md",f"# 1. {it.name.split('_',1)[0]} 迭代目标\n\n- **Status**：{status}\n- **Objective**：{objective}\n")
    if not (turn/"CHECKLIST.md").exists():
        write_md(turn/"CHECKLIST.md","# 1. 当前执行清单\n\n"+section(report,3,"执行清单"))
    if not (turn/"TEST.md").exists():
        write_md(turn/"TEST.md","# 1. 当前验收记录\n\n"+section(report,4,"验收记录"))
    if not (turn/"TURN.md").exists():
        write_md(turn/"TURN.md",f"# 1. {turn.name.split('_',1)[0]} 执行轮次报告\n\n- **Status**：FINALIZED\n\n## 1.1. USER REPORT\n\n{report}")
    # Promote only the reviewed durable subset, preserving frozen content and private input
    for p in [it/"ITERATION.md",turn/"TURN.md",turn/"CHECKLIST.md",turn/"TEST.md"]:
        text=p.read_text(encoding="utf-8")
        lines=text.splitlines(keepends=True)
        if lines and lines[0].startswith("<!-- APCF-META"):
            lines[0]=lines[0].replace('"visibility":"private"','"visibility":"public"')
            p.write_text("".join(lines),encoding="utf-8")
        else: raise SystemExit("FAIL: durable state metadata missing: "+str(p.relative_to(ROOT)))
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
