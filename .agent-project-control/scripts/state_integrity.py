# APCF-META {"schema":1,"visibility":"public"}
import argparse
import re
import subprocess
from pathlib import Path
from common import ROOT, FRAMEWORK_ROOT

SOURCE_RE = re.compile(r"Source TURN[^`]*`([^`]+)`")
CURRENT_REPORT_MARKER = "## 1.1. 最新完整用户报告"
TURN_REPORT_MARKER = "## 1.1. USER REPORT"

def _git_tracked(path):
    path=Path(path)
    rel=path.resolve().relative_to(ROOT.resolve()).as_posix()
    tracked=subprocess.run(["git","rev-parse",":"+rel],cwd=ROOT,capture_output=True,text=True)
    if tracked.returncode: return False
    actual=subprocess.run(["git","hash-object","--path="+rel,str(path)],cwd=ROOT,capture_output=True,text=True)
    return actual.returncode==0 and tracked.stdout.strip()==actual.stdout.strip()

def validate(require_tracked=False):
    errors=[]
    current=ROOT/"CURRENT.md"
    if not current.is_file():
        return ["CURRENT.md missing"]
    text=current.read_text(encoding="utf-8")
    m=SOURCE_RE.search(text)
    if not m:
        if "Latest TR**：不适用" in text or "尚未开始项目执行轮次" in text:
            return []
        return ["CURRENT.md has no Source TURN"]
    turn=(ROOT/m.group(1)).resolve()
    iterations=(FRAMEWORK_ROOT/"iterations").resolve()
    if not turn.is_relative_to(iterations):
        return ["CURRENT Source TURN is outside iterations/"]
    needed=[turn/"TURN.md",turn/"CHECKLIST.md",turn/"TEST.md",turn.parents[1]/"ITERATION.md"]
    for p in needed:
        if not p.is_file():
            errors.append(f"CURRENT Source TURN durable file missing: {p.relative_to(ROOT)}")
    if errors:
        return errors
    if CURRENT_REPORT_MARKER not in text:
        errors.append("CURRENT.md missing latest full report marker")
    else:
        current_report=text.split(CURRENT_REPORT_MARKER,1)[1].strip()
        turn_text=(turn/"TURN.md").read_text(encoding="utf-8")
        if TURN_REPORT_MARKER not in turn_text:
            errors.append("TURN.md missing USER REPORT marker")
        elif current_report != turn_text.split(TURN_REPORT_MARKER,1)[1].strip():
            errors.append("CURRENT.md report body differs from Source TURN/TURN.md")
    index=FRAMEWORK_ROOT/"iterations"/"INDEX.md"
    if not index.is_file():
        errors.append("iterations/INDEX.md missing")
    elif turn.parents[1].name not in index.read_text(encoding="utf-8"):
        errors.append(f"iterations/INDEX.md does not reference current IT: {turn.parents[1].name}")
    if require_tracked:
        for p in [current,index,*needed]:
            if not _git_tracked(p):
                errors.append(f"current durable state is not Git-tracked or index differs: {p.relative_to(ROOT)}")
    return errors

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--require-tracked",action="store_true")
    a=ap.parse_args()
    errors=validate(a.require_tracked)
    if errors:
        for e in errors: print("FAIL:",e)
        raise SystemExit(2)
    print("PASS: CURRENT and Source TURN durable state are consistent" + (" and tracked" if a.require_tracked else ""))

if __name__=="__main__":
    main()
