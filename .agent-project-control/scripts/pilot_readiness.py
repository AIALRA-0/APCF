# APCF-META {"schema":1,"visibility":"public"}
import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

from common import ROOT, FRAMEWORK_ROOT
from test_ledger import validate_file

SCRIPTS=FRAMEWORK_ROOT/"scripts"


def run(name,*args):
    r=subprocess.run(
        [sys.executable,"-B",str(SCRIPTS/name),*map(str,args)],
        cwd=ROOT,capture_output=True,text=True,encoding="utf-8"
    )
    if r.returncode:
        print(r.stdout,end="")
        print(r.stderr,end="",file=sys.stderr)
        raise SystemExit(f"FAIL: {name} exited {r.returncode}")
    return r.stdout


def runtime_artifacts():
    out=[]
    for p in (FRAMEWORK_ROOT/"runtime").rglob("*"):
        if p.is_file() and p.name!=".apcf-dir.yaml":
            out.append(p)
    return out


def current_turn():
    import re
    text=(ROOT/"CURRENT.md").read_text(encoding="utf-8")
    m=re.search(r"Source TURN[^`]*`([^`]+)`",text)
    return (ROOT/m.group(1)).resolve() if m else None


def validate_distribution(path):
    c=Path(path)
    errors=[]
    control=c/".agent-project-control"
    if not (c/"AGENTS.md").is_file(): errors.append("distribution missing AGENTS.md")
    if not (c/"CURRENT.md").is_file(): errors.append("distribution missing CURRENT.md")
    if not control.is_dir(): errors.append("distribution missing .agent-project-control")
    if control.is_dir() and not (control/"design/INDEX.md").is_file(): errors.append("distribution missing shared design baseline")
    if control.is_dir() and (control/"DESIGN.md").is_file():
        design_text=(control/"DESIGN.md").read_text(encoding="utf-8")
        if "**采用状态**：`UNRESOLVED`" not in design_text or "**Profile 状态**：`UNRESOLVED`" not in design_text: errors.append("distribution project DESIGN auto-adopted a shared Profile")
    if control.is_dir():
        if any((control/"iterations").glob("IT-*")): errors.append("distribution leaked template IT/TR history")
        if any((control/"materials").glob("MAT-*")): errors.append("distribution leaked template materials")
        if any((control/"regressions").glob("REG-*")): errors.append("distribution leaked source regression instances")
        if any((control/"decisions").glob("ADR-*")): errors.append("distribution leaked source ADR instances")
        if any((control/"runbooks").glob("RB-*")): errors.append("distribution leaked source runbook instances")
        cfg=(control/"framework.yaml").read_text(encoding="utf-8")
        if "template_source: false" not in cfg: errors.append("distribution framework.yaml is not downstream mode")
    cur=(c/"CURRENT.md").read_text(encoding="utf-8") if (c/"CURRENT.md").exists() else ""
    if "Latest TR**：不适用" not in cur: errors.append("distribution CURRENT.md is not clean initial state")
    return errors


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--full",action="store_true")
    ap.add_argument("--require-clean",action="store_true")
    a=ap.parse_args()

    cfg=(FRAMEWORK_ROOT/"framework.yaml").read_text(encoding="utf-8")
    if 'schema_version: "0.3.0"' not in cfg:
        raise SystemExit("FAIL: framework.yaml is not v0.3.0")

    for p in SCRIPTS.glob("*.py"):
        compile(p.read_bytes(),str(p),"exec")

    run("lint_framework.py")
    run("report_contract_selfcheck.py")
    run("core_repair_selfcheck.py")
    run("design_contract.py","--check")
    tr=current_turn()
    if tr:
        errors=validate_file(tr/"TEST.md", tr/"CHECKLIST.md")
        if errors:
            for e in errors: print("FAIL:",e)
            raise SystemExit(2)

    if a.full:
        print(run("supervisor_selfcheck.py"),end="")
        print(run("selfcheck.py"),end="")

    if a.require_clean:
        # Readiness must never delete evidence. Report actual residue without mutation.
        run("state_integrity.py","--require-tracked")
        artifacts=runtime_artifacts()
        if artifacts:
            for p in artifacts:
                print("FAIL: runtime artifact remains:",p.relative_to(ROOT))
            raise SystemExit(2)
        preview=run("compact_template_source.py")
        if any(line.startswith("DRY-RUN ") for line in preview.splitlines()):
            print(preview,end="")
            raise SystemExit("FAIL: template source still has removable history; review and compact first")

    # A real project is not a template source. Do not demand replacing its native
    # README or repackaging its facts. Distribution packaging has its own explicit check.
    with tempfile.TemporaryDirectory(dir=FRAMEWORK_ROOT/"runtime/testbed") as td:
        out=Path(td)/"bootstrap-probe"
        run("bootstrap.py",out)
        errors=validate_distribution(out)
        if errors:
            for e in errors:print("FAIL:",e)
            raise SystemExit(2)

    print("PASS: APCF v0.3.0 deterministic pre-pilot readiness")


if __name__=="__main__":
    main()
