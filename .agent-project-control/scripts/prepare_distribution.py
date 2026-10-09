# APCF-META {"schema":1,"visibility":"public"}
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from bootstrap import populate_target
from common import ROOT, FRAMEWORK_ROOT, now_stamp, dir_marker, parse_meta


ROOT_DOCUMENTS = [
    "README.md",
    "README.en.md",
    "TEMPLATE_SPEC.md",
    "CODEX_PROMPT.md",
    "CODEX_DEPLOY.md",
    "PILOT_TEST_PLAN.md",
    "VALIDATION.md",
    ".gitignore",
]
EXAMPLE_IGNORES = {".git", "__pycache__", ".venv", "node_modules"}


def _visibility(path: Path):
    meta = parse_meta(path / ".apcf-dir.yaml") if path.is_dir() else parse_meta(path)
    if meta is None and not path.is_dir():
        meta = parse_meta(path.with_name(path.name + ".apcf-meta.yaml"))
    return (meta or {}).get("visibility")


def _copy_root_documents(target: Path) -> None:
    for name in ROOT_DOCUMENTS:
        source = ROOT / name
        if not source.is_file() or source.is_symlink():
            raise SystemExit("FAIL: required public distribution document is missing: " + name)
        if _visibility(source) != "public":
            raise SystemExit("FAIL: required distribution document must be explicitly public: " + name)
        shutil.copy2(source, target / name)


def _ignore_examples(directory, names):
    ignored = []
    for name in names:
        item = Path(directory) / name
        if (
            item.is_symlink()
            or name in EXAMPLE_IGNORES
            or name.endswith(".pyc")
            or _visibility(item) == "private"
        ):
            ignored.append(name)
            continue
        if _visibility(item) not in {"public", "private"}:
            rel = item.relative_to(ROOT).as_posix()
            raise SystemExit("FAIL: synthetic example has no visibility metadata: " + rel)
    return ignored


def _copy_examples(target: Path) -> None:
    source = ROOT / "examples"
    if source.is_symlink() or not source.is_dir() or _visibility(source) == "private":
        raise SystemExit("FAIL: public synthetic examples/ directory is required for distribution")
    shutil.copytree(source, target / "examples", ignore=_ignore_examples)


def _render_target_tree(target: Path) -> None:
    control = target / ".agent-project-control"
    scripts = control / "scripts"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        value for value in (str(scripts), env.get("PYTHONPATH", "")) if value
    )
    subprocess.run(
        [sys.executable, "-B", str(scripts / "render_tree.py")],
        env=env,
        check=True,
    )


def _run_design_contract(target: Path, action: str) -> None:
    script = target / ".agent-project-control" / "scripts" / "design_contract.py"
    if script.is_symlink() or not script.is_file():
        raise SystemExit("FAIL: Design contract script is missing or unsafe")
    result = subprocess.run([sys.executable, "-B", str(script), action], check=False)
    if result.returncode:
        raise SystemExit(f"FAIL: design_contract.py {action} rejected {target} (exit {result.returncode})")


def _inventory(root: Path) -> dict:
    files = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SystemExit("FAIL: distribution candidate contains a symlink: " + path.relative_to(root).as_posix())
        if path.is_file():
            payload = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(root).as_posix(),
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
    return {"schema": 1, "visibility": "private", "files": files}


def _write_manifest(path: Path, data: dict) -> Path:
    if path.exists() or path.is_symlink():
        raise SystemExit("FAIL: manifest output already exists")
    if not path.parent.is_dir():
        raise SystemExit("FAIL: manifest parent directory must already exist")

    handle, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary = Path(raw_temp)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        temporary.rename(path)
        return path
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", help="new output directory; defaults to runtime/distribution/<timestamp>")
    parser.add_argument("--manifest", help="optional private JSON inventory written outside the candidate")
    parser.add_argument(
        "--profile",
        choices=("core",),
        default=None,
        help="build a Core-only candidate without optional design/components; omitted keeps the existing distribution behavior",
    )
    args = parser.parse_args()

    output = Path(args.output).expanduser().resolve() if args.output else (
        FRAMEWORK_ROOT / "runtime" / "distribution" / f"agent-project-control-{now_stamp()}"
    ).resolve()
    if output.exists() or output.is_symlink():
        raise SystemExit("FAIL: output exists; distribution generation never merges or overwrites")
    if not output.parent.is_dir():
        raise SystemExit("FAIL: output parent directory must already exist")

    manifest = Path(args.manifest).expanduser().resolve() if args.manifest else None
    if manifest is not None:
        try:
            manifest.relative_to(output)
        except ValueError:
            pass
        else:
            raise SystemExit("FAIL: private manifest must be outside the distribution candidate")
        if manifest.exists() or manifest.is_symlink():
            raise SystemExit("FAIL: manifest output already exists")
        if not manifest.parent.is_dir():
            raise SystemExit("FAIL: manifest parent directory must already exist")

    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.distribution-staging-", dir=output.parent))
    manifest_written = False
    try:
        if args.profile == "core":
            # Validate the source registry before filtering it. Otherwise a damaged
            # optional component could disappear silently from the Core candidate.
            _run_design_contract(ROOT, "--check")
        populate_target(staging, profile=args.profile)
        if args.profile == "core":
            # INDEX is a generated view of the candidate's actual registrations.
            _run_design_contract(staging, "--sync")
            _run_design_contract(staging, "--check")
        _copy_root_documents(staging)
        _copy_examples(staging)
        # The candidate contents are the explicit public distribution surface;
        # the enclosing runtime/distribution directory remains private.
        dir_marker(staging, "public")
        # Bootstrap rendered before public documents and examples were copied.
        # Refresh the complete candidate tree before its hashes enter the manifest.
        _render_target_tree(staging)

        if manifest is not None:
            _write_manifest(manifest, _inventory(staging))
            manifest_written = True

        staging.rename(output)
        if manifest is not None:
            print("PRIVATE MANIFEST: " + manifest.as_posix())
        print(output)
    except BaseException:
        if manifest_written and manifest is not None:
            manifest.unlink(missing_ok=True)
        raise
    finally:
        if staging.exists():
            shutil.rmtree(staging)


if __name__ == "__main__":
    main()
