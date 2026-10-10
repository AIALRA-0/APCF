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
ROOT_MARKERS = ["AGENTS.md", "CURRENT.md", "APCF-START.md", ".agent-project-control", ".aialra"]


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

    from distribution_policy import copy_core
    try:
        copy_core(ROOT,target,install_only=True)
    except (OSError,ValueError) as exc:
        raise SystemExit('FAIL: explicit Core member policy rejected installation: '+str(exc))

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

    render_env = os.environ.copy()
    render_scripts = str(control / "scripts")
    render_env["PYTHONPATH"] = os.pathsep.join(
        value for value in (render_scripts, render_env.get("PYTHONPATH", "")) if value
    )
    # 最小 Core 不携带可选组件，索引必须由目标中实际登记的组件派生
    for action in ('--sync', '--check'):
        subprocess.run(
            [sys.executable, '-B', str(control / 'scripts' / 'design_contract.py'), action],
            env=render_env,
            check=True,
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
    created_dirs: list[tuple[Path, tuple[int, int]]] = []
    installed_files: list[tuple[Path, tuple[int, int]]] = []
    codex_dirs = [target / ".codex", target / ".codex" / "skills"]
    try:
        for directory in codex_dirs:
            if not directory.exists():
                directory.mkdir()
                created_dirs.append((directory, _identity(directory)))

        file_paths = [
            Path("AGENTS.md"),
            Path("CURRENT.md"),
            Path("APCF-START.md"),
            Path(".codex/.apcf-dir.yaml"),
            Path(".codex/skills/.apcf-dir.yaml"),
        ]
        for relative in file_paths:
            source = staging / relative
            destination = target / relative
            if destination.exists():
                continue
            # Create in the real destination so NTFS inherits its actual parent ACL.
            # Exclusive creation preserves refusal to replace concurrent objects.
            with destination.open('xb') as output:
                installed_files.append((destination, _identity(destination)))
                with source.open('rb') as input_stream:
                    shutil.copyfileobj(input_stream, output)

        # Native entry documents are not rewritten or guessed public. A missing
        # classification gets a private hash sidecar; a real existing marker stays intact.
        import hashlib
        for name in ('README.md','README.en.md','TEMPLATE_SPEC.md','CODEX_PROMPT.md','CODEX_DEPLOY.md','PILOT_TEST_PLAN.md','VALIDATION.md'):
            native=target/name;side=target/(name+'.apcf-meta.yaml')
            if native.is_file() and parse_meta(native) is None and not side.exists():
                if native.is_symlink() or side.is_symlink():raise ValueError('unsafe native document metadata path')
                raw=native.read_bytes()
                with side.open('xb') as stream:
                    installed_files.append((side,_identity(side)))
                    stream.write(('# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\nsha256: '+hashlib.sha256(raw).hexdigest()+'\n').encode())
        staged_control = staging / ".agent-project-control"
        destination_control = target / ".agent-project-control"
        destination_control.mkdir()
        created_dirs.append((destination_control, _identity(destination_control)))
        for source in sorted(staged_control.rglob('*')):
            destination = destination_control / source.relative_to(staged_control)
            if source.is_dir():
                destination.mkdir()
                created_dirs.append((destination, _identity(destination)))
            else:
                with destination.open('xb') as output:
                    installed_files.append((destination, _identity(destination)))
                    with source.open('rb') as input_stream:
                        shutil.copyfileobj(input_stream, output)
    except BaseException:
        for path, identity in reversed(installed_files):
            if path.exists() and _identity(path) == identity:
                path.unlink()
        for directory, identity in reversed(created_dirs):
            try:
                if directory.exists() and _identity(directory) == identity:
                    directory.rmdir()
            except OSError:
                pass
        raise


def install_clean_shell(raw_target: str) -> Path:
    """Install without replacing an existing directory or changing its ACL/mode.

    Existing empty and populated roots both use the same per-object transaction.
    A failed staged build never removes the caller's original root directory.
    """
    _validate_source_framework()
    target, existed, _ = _preflight_target(raw_target)
    staging = Path(tempfile.mkdtemp(prefix=f".{target.name}.apcf-staging-", dir=target.parent))
    created_root = None
    try:
        populate_target(staging)
        if not existed:
            target.mkdir()
            created_root = _identity(target)
        _install_into_existing_project(target, staging)
        print("PASS: clean control shell installed without source-template history")
        return target
    except BaseException:
        if created_root is not None and target.exists() and _identity(target) == created_root:
            try:
                target.rmdir()  # Keep any unknown concurrent contents; never recurse.
            except OSError:
                pass
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
