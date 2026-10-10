# APCF-META {"schema":1,"visibility":"public"}
import argparse
import shutil
import stat
import time
from common import FRAMEWORK_ROOT

SCAFFOLD = {"testbed", "runs", "downloads", "tmp", "cache", "large", "distribution"}


def remove_readonly(func, path, exc):
    if not isinstance(exc[1], PermissionError):
        raise exc[1]
    from pathlib import Path
    Path(path).chmod(stat.S_IWRITE | stat.S_IREAD)
    func(path)


def main():
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--older-than-hours", type=float)
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        from retention_guard import deny_blanket_cleanup
        deny_blanket_cleanup()
    runtime = (FRAMEWORK_ROOT / "runtime").resolve()
    if not runtime.is_relative_to(FRAMEWORK_ROOT.resolve()) or runtime == FRAMEWORK_ROOT.resolve():
        raise SystemExit("FAIL: unsafe runtime root")
    if args.all:
        targets = []
        for entry in runtime.iterdir():
            if entry.name == ".apcf-dir.yaml":
                continue
            if entry.is_dir() and entry.name in SCAFFOLD:
                targets.extend(p for p in entry.iterdir() if p.name != ".apcf-dir.yaml")
            else:
                targets.append(entry)
    else:
        now = time.time()
        targets = [p for p in runtime.rglob("*") if p.is_file() and p.name != ".apcf-dir.yaml"
                   and now - p.stat().st_mtime >= args.older_than_hours * 3600]
    if args.apply:
        from selfcheck_runlog import validate_runlog_references
        protected, reference_errors = validate_runlog_references(runtime / 'runs')
        legacy_log = runtime / 'runs/selfcheck.json'
        if legacy_log.exists() or legacy_log.is_symlink():
            protected.update(path.resolve() for path in
                             (legacy_log, legacy_log.with_name(legacy_log.name + '.apcf-meta.yaml')))
        if reference_errors:
            raise SystemExit('FAIL: selfcheck evidence references are invalid; cleanup refused: '
                             + '; '.join(reference_errors))
        for target in targets:
            resolved = target.resolve()
            if any(path == resolved or path.is_relative_to(resolved) for path in protected):
                raise SystemExit('FAIL: cleanup would remove referenced selfcheck evidence: ' + str(target))
    # Validate every absolute target and descendant before any deletion.
    for target in targets:
        resolved = target.resolve()
        if target.is_symlink() or not resolved.is_relative_to(runtime) or resolved == runtime:
            raise SystemExit("FAIL: unsafe cleanup target: " + str(target))
        for child in target.rglob("*") if target.is_dir() else []:
            if child.is_symlink() or not child.resolve().is_relative_to(resolved):
                raise SystemExit("FAIL: escaped cleanup child: " + str(child))
    for target in targets:
        print(("DELETE " if args.apply else "DRY-RUN ") + str(target))
        if args.apply:
            if target.is_dir():
                shutil.rmtree(target, onerror=remove_readonly)
            else:
                target.unlink(missing_ok=True)
    print(f"INVENTORY_ONLY: {len(targets)} objects; this is not permission to delete them")


if __name__ == "__main__":
    main()
