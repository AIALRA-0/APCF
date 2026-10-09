# APCF-META {"schema":1,"visibility":"public"}
"""Run focused regressions for metadata scope, frozen history, and run logs."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from common import FRAMEWORK_ROOT
from lint_framework import (
    FROZEN_HASH_SCOPE,
    directory_tree_sha256,
    managed_text_files,
    metadata_errors,
    runtime_boundary_errors,
    validate_frozen_directory_markers,
)
from selfcheck_runlog import (
    PRIVATE_HEADER,
    make_run_id,
    store_run,
    validate_runlog_references,
    validate_summary_reference,
)

def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _frozen_meta(repo: Path, directory: Path, freeze_id: str) -> dict:
    repo = Path(repo).resolve()
    directory = Path(directory).resolve()
    if not isinstance(freeze_id, str) or not freeze_id.strip():
        raise ValueError("freeze identity must be a nonempty string")
    try:
        relative_path = directory.relative_to(repo).as_posix()
    except ValueError as error:
        raise ValueError("frozen directory escapes the supplied repository root") from error
    return {
        "schema": 1,
        "visibility": "private",
        "kind": "directory",
        "path": relative_path,
        "sha256": directory_tree_sha256(directory),
        "freeze_id": freeze_id,
        "hash_scope": FROZEN_HASH_SCOPE,
    }


def create_frozen_marker(repo: Path, directory: Path, freeze_id: str) -> dict:
    """Add one private marker without replacing existing content."""
    repo = Path(repo).resolve()
    directory = Path(directory)
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError(f"expected frozen directory missing or unsafe: {directory}")
    meta = _frozen_meta(repo, directory, freeze_id)
    marker = directory / ".apcf-dir.yaml"
    expected_text = (
        "# APCF-META " + json.dumps(meta, ensure_ascii=False, separators=(",", ":")) + "\n"
        "schema: 1\nvisibility: private\n"
    )
    if marker.exists() or marker.is_symlink():
        if marker.is_symlink():
            raise ValueError(f"existing frozen marker is unsafe: {marker}")
        try:
            current = marker.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise ValueError(f"existing frozen marker is unreadable: {marker}") from error
        if current != expected_text:
            raise FileExistsError(f"existing frozen marker differs; refusing to overwrite: {marker}")
    else:
        with marker.open("xb") as stream:
            stream.write(expected_text.encode("utf-8"))
            stream.flush()
            os.fsync(stream.fileno())
    return meta


def _dir_marker(directory: Path, visibility: str = "private") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".apcf-dir.yaml").write_text(
        f'# APCF-META {{"schema":1,"visibility":"{visibility}"}}\n'
        f"schema: 1\nvisibility: {visibility}\n",
        encoding="utf-8",
    )


def _test_runtime_scope(test_root: Path) -> dict:
    repo = test_root / "repo"
    framework = repo / ".agent-project-control"
    runtime = framework / "runtime"
    standard_names = ("testbed", "runs", "downloads", "tmp", "cache", "large", "distribution")
    _dir_marker(runtime)
    for name in standard_names:
        _dir_marker(runtime / name)
    deep = runtime / "cache" / "node_modules" / "vendor-package"
    deep.mkdir(parents=True)
    for suffix in (".md", ".yaml", ".py", ".html"):
        (deep / f"temporary{suffix}").write_text("third party temporary content\n", encoding="utf-8")

    scanned = managed_text_files(framework)
    if any(path.is_relative_to(runtime) for path in scanned):
        raise AssertionError("runtime temporary files entered the managed scan")
    if metadata_errors(scanned, root=repo):
        raise AssertionError("third party runtime files produced metadata errors")

    missing_source = framework / "scripts" / "new_managed.py"
    missing_source.parent.mkdir(parents=True, exist_ok=True)
    missing_source.write_text("print('managed')\n", encoding="utf-8")
    missing_errors = metadata_errors(managed_text_files(framework), root=repo)
    normalized_missing = [error.replace("\\", "/") for error in missing_errors]
    if len(normalized_missing) != 1 or "scripts/new_managed.py" not in normalized_missing[0]:
        raise AssertionError(f"non-runtime missing metadata was not rejected: {missing_errors}")

    marker_failures = []
    marker_paths = [runtime / ".apcf-dir.yaml", *(runtime / name / ".apcf-dir.yaml" for name in standard_names)]
    for marker in marker_paths:
        original = marker.read_bytes()
        marker.unlink()
        errors = runtime_boundary_errors(framework)
        if not any(marker.name in error and marker.parent.name in error for error in errors):
            raise AssertionError(f"missing runtime marker was not rejected: {marker}")
        marker.write_bytes(original)
        marker_failures.append(marker.relative_to(repo).as_posix())

    public_marker = runtime / "cache" / ".apcf-dir.yaml"
    _dir_marker(public_marker.parent, visibility="public")
    errors = runtime_boundary_errors(framework)
    if not any("private visibility" in error and "cache" in error for error in errors):
        raise AssertionError("public runtime marker was not rejected")
    return {
        "deep_temporary_files_excluded": 4,
        "non_runtime_missing_metadata_rejected": missing_errors[0],
        "missing_runtime_markers_rejected": marker_failures,
        "public_runtime_marker_rejected": True,
    }


def _test_frozen_history(test_root: Path) -> dict:
    repo = test_root / "history-repo"
    freeze_id = "synthetic-freeze-001"
    base = repo / "synthetic-history" / "evidence"
    directories = [base / "case", base / "case" / "reports", base / "case" / "reports" / "evidence"]
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)
        payload = directory / "payload.bin"
        payload.write_bytes(b"frozen payload\n")
    created = [create_frozen_marker(repo, directory, freeze_id) for directory in directories]
    errors = validate_frozen_directory_markers(directories, root=repo)
    if errors or len(created) != 3:
        raise AssertionError(f"frozen marker fixture did not validate: {errors}")

    marker = directories[0] / ".apcf-dir.yaml"
    original_marker = marker.read_bytes()
    rejected_identity_fields = []
    for field, value in (
        ("path", "*"),
        ("visibility", "public"),
        ("freeze_id", ""),
        ("hash_scope", "unknown-scope"),
    ):
        lines = original_marker.decode("utf-8").splitlines()
        identity = json.loads(lines[0].removeprefix("# APCF-META "))
        identity[field] = value
        marker.write_text(
            "# APCF-META " + json.dumps(identity, ensure_ascii=False, separators=(",", ":")) + "\n"
            + "\n".join(lines[1:]) + "\n",
            encoding="utf-8",
        )
        identity_errors = validate_frozen_directory_markers(directories, root=repo)
        marker.write_bytes(original_marker)
        if not identity_errors:
            raise AssertionError(f"production linter accepted forged frozen marker field: {field}")
        rejected_identity_fields.append(field)

    drifted = directories[-1] / "payload.bin"
    drifted.write_bytes(b"changed payload\n")
    drift_errors = validate_frozen_directory_markers(directories, root=repo)
    if not any("SHA drift" in error for error in drift_errors):
        raise AssertionError("production linter did not reject frozen history SHA drift")
    return {
        "synthetic_marker_count": len(created),
        "forged_identity_fields_rejected_by_production_linter": rejected_identity_fields,
        "sha_drift_rejected_by_production_linter": True,
    }


def _test_runlog(test_root: Path) -> dict:
    runtime_runs = test_root / "runtime" / "runs"
    _dir_marker(runtime_runs)
    pass_id = make_run_id()
    pass_rows = [{"case": "expected-negative", "exit_code": 2, "expected_exit_code": 2, "stdout": "one raw copy"}]
    pass_summary = store_run(runtime_runs, pass_rows, "PASS", run_id=pass_id)
    raw_path = runtime_runs / pass_summary["raw_path"]
    summary_path = runtime_runs / f"{pass_id}.summary.json"
    raw_before = raw_path.read_bytes()
    summary_before = summary_path.read_bytes()
    if _sha256(raw_before) != pass_summary["raw_sha256"] or b"stdout" in summary_before:
        raise AssertionError("raw SHA or summary size contract failed")
    if pass_summary["run_outcome"] != "PASS" or pass_summary["expected_exit_code_mismatches"] != 0:
        raise AssertionError("expected nonzero test exit incorrectly changed the run outcome")

    fail_id = make_run_id()
    fail_summary = store_run(
        runtime_runs,
        [{"case": "unexpected-failure", "exit_code": 1, "expected_exit_code": 0, "stderr": "actual failure"}],
        "FAIL",
        run_id=fail_id,
    )
    if fail_summary["run_outcome"] != "FAIL" or fail_summary["expected_exit_code_mismatches"] != 1:
        raise AssertionError("selfcheck failure was not recorded accurately")

    try:
        store_run(runtime_runs, pass_rows, "PASS", run_id=pass_id)
    except FileExistsError:
        pass
    else:
        raise AssertionError("duplicate run ID was not rejected")
    if raw_path.read_bytes() != raw_before or summary_path.read_bytes() != summary_before:
        raise AssertionError("duplicate run ID changed an existing log")

    protected, reference_errors = validate_runlog_references(runtime_runs)
    if reference_errors or len(protected) != 8:
        raise AssertionError(f"complete run references did not validate: {reference_errors}")

    missing_id = make_run_id()
    missing_summary = store_run(
        runtime_runs,
        [{"case": "missing-raw-reference", "exit_code": 1, "expected_exit_code": 0}],
        "FAIL",
        run_id=missing_id,
    )
    missing_raw = runtime_runs / missing_summary["raw_path"]
    missing_raw.unlink()
    missing_summary_path = runtime_runs / f"{missing_id}.summary.json"
    missing_protected, missing_errors = validate_summary_reference(missing_summary_path, runtime_runs)
    if not any("referenced raw log missing" in error for error in missing_errors):
        raise AssertionError("summary with missing raw reference did not block cleanup")
    if missing_raw.resolve(strict=False) not in missing_protected:
        raise AssertionError("missing raw path was not returned as protected")
    all_protected, aggregate_errors = validate_runlog_references(runtime_runs)
    if not aggregate_errors or missing_raw.resolve(strict=False) not in all_protected:
        raise AssertionError("aggregate cleanup guard ignored the missing log reference")
    return {
        "unique_run_ids": [pass_id, fail_id, missing_id],
        "expected_nonzero_kept_pass": True,
        "real_fail_kept_fail": True,
        "duplicate_id_rejected": True,
        "missing_reference_blocks_cleanup": True,
        "complete_chain_protected_file_count": len(protected),
        "run_summaries": [
            {
                key: summary[key]
                for key in (
                    "run_id", "run_outcome", "raw_path", "raw_sha256", "raw_bytes",
                    "expected_exit_code_mismatches",
                )
            }
            for summary in (pass_summary, fail_summary, missing_summary)
        ],
        "missing_reference_errors": missing_errors,
    }


def _evidence_sidecar(path: Path, data: bytes) -> bytes:
    return (
        f"{PRIVATE_HEADER}\n"
        "schema: 1\nvisibility: private\nkind: file\n"
        f"path: {path.name}\nsha256: {_sha256(data)}\n"
    ).encode("utf-8")


def run_checks(evidence_path: Path | None = None, fixture_root: Path | None = None) -> tuple[dict, int]:
    """Run isolated synthetic regressions without reading source history or runtime state."""
    fixture_root = Path(fixture_root or FRAMEWORK_ROOT / "runtime" / "testbed")
    if fixture_root.is_symlink() or not fixture_root.is_dir():
        raise ValueError("runtime/testbed fixture root missing or unsafe")
    results = []
    with tempfile.TemporaryDirectory(prefix="metadata-selfcheck-", dir=fixture_root) as temporary:
        test_root = Path(temporary)
        for name, test in (
            ("runtime_scope", _test_runtime_scope),
            ("frozen_history", _test_frozen_history),
            ("selfcheck_runlog", _test_runlog),
        ):
            try:
                results.append({"case": name, "status": "PASS", "result": test(test_root)})
            except Exception as error:
                results.append({"case": name, "status": "FAIL", "error": f"{type(error).__name__}: {error}"})

    passed = all(row["status"] == "PASS" for row in results)
    payload = {
        "schema": 1,
        "visibility": "private",
        "suite": "metadata-selfcheck",
        "result": "PASS" if passed else "FAIL",
        "checks": results,
        "scope_boundary": "Core staging and ZIP leakage remain assigned to the main TR",
    }
    if evidence_path is not None:
        evidence_path = Path(evidence_path)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        evidence_data = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        evidence_path.write_bytes(evidence_data)
        evidence_path.with_name(evidence_path.name + ".apcf-meta.yaml").write_bytes(
            _evidence_sidecar(evidence_path, evidence_data)
        )
    for row in results:
        print(f"{row['status']}: {row['case']}")
    return payload, 0 if passed else 2


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Run focused APCF metadata and selfcheck log regressions")
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--fixture-root", type=Path, default=FRAMEWORK_ROOT / "runtime" / "testbed")
    args = parser.parse_args()
    if not args.run:
        parser.error("--run is required")
    try:
        _, code = run_checks(args.evidence, args.fixture_root)
        return code
    except Exception as error:
        print(f"FAIL: {type(error).__name__}: {error}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
