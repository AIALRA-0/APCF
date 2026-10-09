# APCF-META {"schema":1,"visibility":"public"}
import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from common import ROOT, FRAMEWORK_ROOT, parse_meta, dir_marker, write_md


OPERATIONAL = {"iterations", "regressions", "decisions", "runbooks", "materials", "runtime"}
INDEX_TITLES = {
    "iterations": "# 1. IT 迭代索引\n",
    "regressions": "# 1. REG 回归问题索引\n",
    "decisions": "# 1. ADR 架构决策索引\n",
    "runbooks": "# 1. RB 运行手册索引\n",
    "materials": "# 1. MAT 材料索引\n",
}
RUNTIME_DIRS = ["testbed", "runs", "downloads", "tmp", "cache", "large", "distribution"]
ROOT_MARKERS = ["AGENTS.md", "CURRENT.md", ".agent-project-control", ".aialra"]


def _visibility(path: Path):
    meta = parse_meta(path / ".apcf-dir.yaml") if path.is_dir() else parse_meta(path)
    if meta is None and not path.is_dir():
        meta = parse_meta(path.with_name(path.name + ".apcf-meta.yaml"))
    return (meta or {}).get("visibility")


def _ignore_framework(path, names, profile=None):
    rel = Path(path).relative_to(FRAMEWORK_ROOT)
    if not rel.parts:
        return [name for name in names if name in OPERATIONAL]
    ignored = []
    for name in names:
        item = Path(path) / name
        if (
            item.is_symlink()
            or name == "__pycache__"
            or name.endswith(".pyc")
            or _visibility(item) == "private"
        ):
            ignored.append(name)
    if profile == "core" and rel.parts == ("design",) and "components" in names:
        ignored.append("components")
    return ignored


def _normalize_framework_metadata(text: str) -> str:
    source_values = re.findall(r"(?m)^template_source:[ \t]*([^\r\n]*)$", text)
    status_values = re.findall(r"(?m)^status:[ \t]*([^\r\n]*)$", text)
    if (
        len(source_values) != 1
        or source_values[0].strip() not in {"true", "false"}
        or len(status_values) != 1
        or re.fullmatch(r'"[^"\r\n]*"', status_values[0].strip()) is None
    ):
        raise SystemExit("FAIL: source framework metadata must contain one boolean template_source and one quoted status field")

    text, source_mode_count = re.subn(
        r"(?m)^template_source:[ \t]*(?:true|false)[ \t]*$",
        "template_source: false",
        text,
    )
    text, status_count = re.subn(
        r'(?m)^status:[ \t]*"[^"\r\n]*"[ \t]*$',
        'status: "uninitialized"',
        text,
    )
    if source_mode_count != 1 or status_count != 1:
        raise SystemExit("FAIL: source framework metadata normalization was not unique")
    return text


def _validate_source_framework() -> None:
    config = FRAMEWORK_ROOT / "framework.yaml"
    if config.is_symlink() or not config.is_file():
        raise SystemExit("FAIL: source framework.yaml is missing or unsafe")
    _normalize_framework_metadata(config.read_text(encoding="utf-8"))


def populate_target(target: Path, profile: str | None = None) -> None:
    """Populate an empty, private staging directory with the generic control shell."""
    if profile not in {None, "core"}:
        raise SystemExit("FAIL: unsupported distribution profile: " + str(profile))
    _validate_source_framework()
    target = Path(target)
    if any(target.iterdir()):
        raise SystemExit("FAIL: internal staging target must be empty")

    shutil.copy2(ROOT / "AGENTS.md", target / "AGENTS.md")
    shutil.copytree(
        FRAMEWORK_ROOT,
        target / ".agent-project-control",
        ignore=lambda path, names: _ignore_framework(path, names, profile=profile),
    )

    control = target / ".agent-project-control"
    for name in OPERATIONAL:
        directory = control / name
        dir_marker(directory, "private" if name == "runtime" else "public")
        if name == "runtime":
            for child in RUNTIME_DIRS:
                dir_marker(directory / child, "private")
        else:
            write_md(directory / "INDEX.md", INDEX_TITLES[name])

    config = control / "framework.yaml"
    config.write_text(_normalize_framework_metadata(config.read_text(encoding="utf-8")), encoding="utf-8")

    write_md(
        target / "CURRENT.md",
        "# 1. 当前状态\n\n- **状态**：尚未开始项目执行轮次\n- **Latest TR**：不适用\n",
    )

    for rel in [".codex/.apcf-dir.yaml", ".codex/skills/.apcf-dir.yaml"]:
        source = ROOT / rel
        if source.is_file():
            destination = target / rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    render_env = os.environ.copy()
    render_scripts = str(control / "scripts")
    render_env["PYTHONPATH"] = os.pathsep.join(
        value for value in (render_scripts, render_env.get("PYTHONPATH", "")) if value
    )
    subprocess.run(
        [sys.executable, "-B", str(control / "scripts" / "render_tree.py")],
        env=render_env,
        check=True,
    )


def _preflight_target(raw_target: str) -> tuple[Path, bool, bool]:
    raw = Path(raw_target).expanduser()
    if raw.is_symlink():
        raise SystemExit("FAIL: target path is a symlink; choose a direct directory path")
    target = raw.resolve()
    if target == ROOT.resolve() or target == FRAMEWORK_ROOT.resolve():
        raise SystemExit("FAIL: target cannot be the source repository or control directory")

    try:
        target.relative_to(ROOT.resolve())
    except ValueError:
        pass
    else:
        runtime = (FRAMEWORK_ROOT / "runtime").resolve()
        try:
            target.relative_to(runtime)
        except ValueError as exc:
            raise SystemExit("FAIL: source-repository targets are allowed only under .agent-project-control/runtime") from exc

    if not target.parent.is_dir():
        raise SystemExit("FAIL: target parent must already exist; no parent directories were created")

    existed = target.exists()
    existed_empty = False
    if existed:
        if not target.is_dir():
            raise SystemExit("FAIL: target exists and is not a directory")
        conflicts = [name for name in ROOT_MARKERS if (target / name).exists() or (target / name).is_symlink()]
        if conflicts:
            raise SystemExit("FAIL: target already contains framework or state files: " + ", ".join(conflicts))
        existed_empty = not any(target.iterdir())

        codex = target / ".codex"
        skills = codex / "skills"
        for path in (codex, skills):
            if path.is_symlink():
                raise SystemExit("FAIL: existing .codex path is a symlink; it was not changed")
        if codex.exists() and not codex.is_dir():
            raise SystemExit("FAIL: existing .codex path is not a directory")
        if skills.exists() and not skills.is_dir():
            raise SystemExit("FAIL: existing .codex/skills path is not a directory")
        for marker in (codex / ".apcf-dir.yaml", skills / ".apcf-dir.yaml"):
            if marker.is_symlink() or (marker.exists() and not marker.is_file()):
                raise SystemExit("FAIL: existing .codex directory marker is not a file")
    return target, existed, existed_empty


def _identity(path: Path) -> tuple[int, int]:
    stat_result = path.stat()
    return stat_result.st_dev, stat_result.st_ino


def _install_into_existing_project(target: Path, staging: Path) -> None:
    created_dirs: list[Path] = []
    installed_files: list[tuple[Path, tuple[int, int]]] = []
    installed_control: tuple[Path, tuple[int, int]] | None = None
    codex_dirs = [target / ".codex", target / ".codex" / "skills"]
    try:
        for directory in codex_dirs:
            if not directory.exists():
                directory.mkdir()
                created_dirs.append(directory)

        file_paths = [
            Path("AGENTS.md"),
            Path("CURRENT.md"),
            Path(".codex/.apcf-dir.yaml"),
            Path(".codex/skills/.apcf-dir.yaml"),
        ]
        for relative in file_paths:
            source = staging / relative
            destination = target / relative
            if destination.exists():
                continue
            os.link(source, destination)
            installed_files.append((destination, _identity(destination)))
            source.unlink()

        staged_control = staging / ".agent-project-control"
        destination_control = target / ".agent-project-control"
        staged_control.rename(destination_control)
        installed_control = (destination_control, _identity(destination_control))
    except BaseException:
        if installed_control is not None:
            path, identity = installed_control
            if path.exists() and _identity(path) == identity:
                resolved = path.resolve()
                if resolved.parent == target.resolve():
                    shutil.rmtree(path)
        for path, identity in reversed(installed_files):
            if path.exists() and _identity(path) == identity:
                path.unlink()
        for directory in reversed(created_dirs):
            try:
                directory.rmdir()
            except OSError:
                pass
        raise


def install_clean_shell(raw_target: str) -> Path:
    _validate_source_framework()
    target, existed, existed_empty = _preflight_target(raw_target)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.apcf-staging-", dir=target.parent))
    removed_empty_target = False
    try:
        populate_target(staging)
        if existed:
            _install_into_existing_project(target, staging)
        else:
            if existed_empty:
                target.rmdir()
                removed_empty_target = True
            staging.rename(target)
        print("PASS: clean control shell installed without source-template history")
        return target
    except BaseException:
        if removed_empty_target and not target.exists():
            target.mkdir()
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="new or empty directory for the APCF control shell")
    args = parser.parse_args()
    install_clean_shell(args.target)


if __name__ == "__main__":
    main()
