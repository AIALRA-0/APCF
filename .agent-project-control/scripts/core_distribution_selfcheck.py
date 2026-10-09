# APCF-META {"schema":1,"visibility":"public"}
"""Run focused positive and negative checks for the Core distribution APIs.

This is deliberately narrower than the framework selfcheck or a project Pilot.
It creates its candidates and native-project fixture only under runtime/runs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

from common import FRAMEWORK_ROOT, ROOT, dir_marker


PREPARE = FRAMEWORK_ROOT / "scripts" / "prepare_distribution.py"
BOOTSTRAP = FRAMEWORK_ROOT / "scripts" / "bootstrap.py"
DESIGN_CONTRACT = FRAMEWORK_ROOT / "scripts" / "design_contract.py"
RUNTIME_RUNS = FRAMEWORK_ROOT / "runtime" / "runs"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise AssertionError("test candidate unexpectedly contains a symlink: " + path.relative_to(root).as_posix())
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha256(path)
    return result


def run(name: str, argv: list[str], commands: list[dict]) -> subprocess.CompletedProcess:
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True, check=False)
    commands.append({
        "name": name,
        "argv": [str(value) for value in argv],
        "exit_code": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    })
    return result


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def component_directories(root: Path) -> list[Path]:
    component_root = root / ".agent-project-control" / "design" / "components"
    if not component_root.exists():
        return []
    return sorted(
        (path for path in component_root.iterdir() if path.is_dir() and not path.is_symlink()),
        key=lambda path: path.name.casefold(),
    )


def design_check(root: Path, label: str, commands: list[dict]) -> subprocess.CompletedProcess:
    return run(label, [sys.executable, "-B", str(root / ".agent-project-control" / "scripts" / "design_contract.py"), "--check"], commands)


def write_report(path: Path, report: dict) -> None:
    sidecar = path.with_name(path.name + ".apcf-meta.yaml")
    if path.exists() or path.is_symlink() or sidecar.exists() or sidecar.is_symlink():
        raise FileExistsError("refusing to overwrite private selfcheck evidence")
    if not path.parent.is_dir():
        raise FileNotFoundError("private evidence directory does not exist")
    payload = (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with path.open("xb") as stream:
        stream.write(payload)
    sidecar_text = (
        '# APCF-META {"schema":1,"visibility":"private"}\n'
        "schema: 1\n"
        "visibility: private\n"
        f"sha256: {hashlib.sha256(payload).hexdigest()}\n"
    )
    with sidecar.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(sidecar_text)


def selfcheck(workspace: Path) -> dict:
    raw = workspace.expanduser()
    if raw.is_symlink():
        raise ValueError("workspace cannot be a symlink")
    workspace = raw.resolve()
    runs_root = RUNTIME_RUNS.resolve()
    if not workspace.is_relative_to(runs_root) or workspace == runs_root:
        raise ValueError("workspace must be a unique child of .agent-project-control/runtime/runs")
    if workspace.exists():
        raise FileExistsError("workspace already exists; selfcheck never merges or overwrites")
    if not workspace.parent.is_dir():
        raise FileNotFoundError("workspace parent must already exist")

    workspace.mkdir()
    dir_marker(workspace, "private")
    candidates = workspace / "candidates"
    dir_marker(candidates, "private")
    default_candidate = candidates / "default"
    core_candidate = candidates / "core"
    commands: list[dict] = []
    checks: list[dict] = []

    default_build = run(
        "default distribution API",
        [sys.executable, "-B", str(PREPARE), "--output", str(default_candidate)],
        commands,
    )
    require(default_build.returncode == 0, "default prepare_distribution invocation failed")
    source_components = component_directories(ROOT)
    candidate_components = component_directories(default_candidate)
    source_ids = [path.name for path in source_components]
    copied_ids = [path.name for path in candidate_components]
    require(source_ids == copied_ids, "default profile did not preserve the source component set")
    require(bool(source_components) or not candidate_components, "a Core source with no optional registrations gained a component")
    default_index = (default_candidate / ".agent-project-control" / "design" / "INDEX.md").read_text(encoding="utf-8")
    for component_id in source_ids:
        require(f"components/{component_id}/COMPONENT.md" in default_index, "default Design INDEX omitted a registered component: " + component_id)
    default_design = design_check(default_candidate, "default Design contract", commands)
    require(default_design.returncode == 0, "default candidate design_contract --check failed")
    checks.append({"id": "default profile compatibility and registered component route", "status": "PASS", "component_ids": source_ids})

    core_build = run(
        "core distribution API",
        [sys.executable, "-B", str(PREPARE), "--output", str(core_candidate), "--profile", "core"],
        commands,
    )
    require(core_build.returncode == 0, "prepare_distribution --profile core failed")
    require(not component_directories(core_candidate), "Core candidate contains an optional design component")
    core_control = core_candidate / ".agent-project-control"
    core_index = (core_control / "design" / "INDEX.md").read_text(encoding="utf-8")
    require("components/" not in core_index, "Core Design INDEX contains an optional component route")
    design_rules = core_control / "design" / "RULES.md"
    rules_text = design_rules.read_text(encoding="utf-8")
    require(re.findall(r"(?m)^## (D\d{2}) ·", rules_text) == [f"D{i:02d}" for i in range(1, 17)], "Core candidate does not preserve D01-D16")
    require((core_control / "design" / "BASELINES.lock.yaml").is_file(), "Core candidate lost the Design baseline lock")
    require((core_control / "design" / "profiles" / "tool-workbench-2.3.1" / "tokens.json").is_file(), "Core candidate lost Profile tokens")
    require((core_control / "interfaces" / "WRITING_STANDARD.md").is_file(), "Core candidate lost Writing interface")
    require((core_control / "interfaces" / "STYLE_STANDARD.md").is_file(), "Core candidate lost Style interface")
    core_design = design_check(core_candidate, "core Design contract", commands)
    require(core_design.returncode == 0, "Core candidate design_contract --check failed")
    design_text = (core_control / "DESIGN.md").read_text(encoding="utf-8")
    require("**采用状态**：`UNRESOLVED`" in design_text, "Core candidate changed Design adoption from UNRESOLVED")
    require("**Profile 状态**：`UNRESOLVED`" in design_text, "Core candidate changed Profile adoption from UNRESOLVED")
    runtime = core_control / "runtime"
    scaffold_names = ["testbed", "runs", "downloads", "tmp", "cache", "large", "distribution"]
    for directory in [runtime, *(runtime / name for name in scaffold_names)]:
        marker = directory / ".apcf-dir.yaml"
        require(marker.is_file() and "visibility: private" in marker.read_text(encoding="utf-8"), "Core runtime scaffold is not private: " + str(directory.relative_to(core_candidate)))
    checks.append({"id": "Core-only positive filter, shared Design retention, no orphan route, and unresolved adoption", "status": "PASS"})

    if source_ids:
        damaged_lock = default_candidate / ".agent-project-control" / "design" / "components" / source_ids[0] / "COMPONENT.lock.json"
    else:
        # A Core source intentionally has no optional registrations. Preserve
        # the same corruption test using a fully valid isolated registration,
        # rather than requiring or reintroducing a real optional dependency.
        component_root = default_candidate / ".agent-project-control" / "design" / "components"
        dir_marker(component_root, "public")
        component = component_root / "synthetic-registration"
        dir_marker(component, "public")
        descriptor = component / "COMPONENT.md"
        descriptor.write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'
                              '# 1. Synthetic optional registration\n\nauto_adopt: false\n', encoding="utf-8")
        damaged_lock = component / "COMPONENT.lock.json"
        damaged_lock.write_text(json.dumps({"schema": 1, "component": component.name,
            "files": {path.name: sha256(path) for path in component.iterdir() if path.is_file()}}, indent=2) + "\n", encoding="utf-8")
        synced = run("synthetic registration index", [sys.executable, "-B", str(default_candidate / ".agent-project-control" / "scripts" / "design_contract.py"), "--sync"], commands)
        require(synced.returncode == 0, "valid synthetic component could not generate its index")
        valid_check = design_check(default_candidate, "valid isolated optional registration", commands)
        require(valid_check.returncode == 0, "synthetic corruption test baseline is not valid")
    registration = json.loads(damaged_lock.read_text(encoding="utf-8"))
    registration["component"] = "damaged-registration"
    damaged_lock.write_text(json.dumps(registration, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    damaged_check = design_check(default_candidate, "damaged component registration negative case", commands)
    damaged_output = damaged_check.stdout + damaged_check.stderr
    require(damaged_check.returncode != 0 and "component registration" in damaged_output.lower(), "design_contract accepted a damaged component registration")
    checks.append({"id": "damaged component registration rejection", "status": "PASS", "rejection": damaged_output.strip()})

    native_project = workspace / "native-project"
    dir_marker(native_project, "private")
    source_file = native_project / "src" / "main.py"
    source_file.parent.mkdir()
    source_file.write_text("VALUE = 'native source stays in place'\n", encoding="utf-8")
    project_config = native_project / "pyproject.toml"
    project_config.write_text("[project]\nname = 'native-project'\nversion = '0.0.0'\n", encoding="utf-8")
    before = inventory(native_project)
    install = run("install Core shell in existing native project", [sys.executable, "-B", str(core_candidate / ".agent-project-control" / "scripts" / "bootstrap.py"), str(native_project)], commands)
    require(install.returncode == 0, "Core bootstrap could not install into the native project fixture")
    after = inventory(native_project)
    for relative, expected_hash in before.items():
        require(after.get(relative) == expected_hash, "bootstrap overwrote native project content: " + relative)
    require("**Latest TR**：不适用" in (native_project / "CURRENT.md").read_text(encoding="utf-8"), "new project CURRENT is not empty of source history")
    checks.append({"id": "native project installation preserves all pre-existing file hashes", "status": "PASS", "source_hashes": before})

    return {
        "schema": 1,
        "visibility": "private",
        "result": "PASS",
        "scope": "focused Core distribution API checks; not full framework selfcheck or Pilot",
        "workspace": workspace.as_posix(),
        "source_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip(),
        "source_components": source_ids,
        "checks": checks,
        "commands": commands,
        "candidate_hashes": {
            "default": hashlib.sha256(json.dumps(inventory(default_candidate), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            "core": hashlib.sha256(json.dumps(inventory(core_candidate), sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Focused Core distribution and bootstrap API checks")
    parser.add_argument("--workspace", required=True, help="new unique path under .agent-project-control/runtime/runs")
    parser.add_argument("--report", help="optional private JSON evidence path; output and sidecar must not exist")
    args = parser.parse_args()
    try:
        result = selfcheck(Path(args.workspace))
        if args.report:
            write_report(Path(args.report).expanduser().absolute(), result)
        for check in result["checks"]:
            print("PASS:", check["id"])
        print("PASS: focused Core distribution checks; workspace=" + result["workspace"])
        if args.report:
            print("PRIVATE EVIDENCE:", Path(args.report).expanduser().absolute())
        return 0
    except (AssertionError, FileExistsError, FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as ex:
        print("FAIL: focused Core distribution checks: " + str(ex))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
