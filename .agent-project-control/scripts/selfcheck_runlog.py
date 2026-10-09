# APCF-META {"schema":1,"visibility":"public"}
"""Persist selfcheck output once and validate every summary-to-raw reference."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import uuid

RUN_ID_PATTERN = re.compile(r"^selfcheck-\d{8}T\d{12}Z-[0-9a-f]{32}$")
PRIVATE_HEADER = '# APCF-META {"schema":1,"visibility":"private"}'


def make_run_id() -> str:
    """Return a collision-resistant UTC identifier shared by CASE and log paths."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"selfcheck-{timestamp}-{uuid.uuid4().hex}"


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sidecar_bytes(object_name: str, payload: bytes) -> bytes:
    return (
        f"{PRIVATE_HEADER}\n"
        "schema: 1\n"
        "visibility: private\n"
        "kind: file\n"
        f"path: {object_name}\n"
        f"sha256: {_sha256(payload)}\n"
    ).encode("utf-8")


def _write_new(path: Path, payload: bytes) -> None:
    """Create a file exclusively and flush its complete byte sequence."""
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _private_runs_marker(runtime_runs: Path) -> list[str]:
    marker = runtime_runs / ".apcf-dir.yaml"
    if marker.is_symlink() or not marker.is_file():
        return ["runtime/runs private directory marker missing or unsafe"]
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0].removeprefix("# APCF-META "))
    except (OSError, UnicodeError, IndexError, json.JSONDecodeError):
        return ["runtime/runs private directory marker is unreadable"]
    if (not isinstance(header, dict) or type(header.get("schema")) is not int or header.get("schema") != 1 or
            header.get("visibility") != "private" or set(header) != {"schema", "visibility"} or
            lines[1:] != ["schema: 1", "visibility: private"]):
        return ["runtime/runs directory marker must declare schema 1 and private visibility"]
    return []


def store_run(runtime_runs: Path, rows: list[dict], run_outcome: str, *, run_id: str) -> dict:
    """Write one immutable raw run and a small SHA-linked summary."""
    if run_outcome not in {"PASS", "FAIL", "BLOCKED", "UNKNOWN"}:
        raise ValueError("unknown selfcheck outcome")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("run ID must contain a UTC timestamp and UUID")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise TypeError("selfcheck rows must be a list of objects")

    runtime_runs = Path(runtime_runs)
    if runtime_runs.is_symlink() or not runtime_runs.is_dir():
        raise ValueError("runtime/runs directory missing or unsafe")
    marker_errors = _private_runs_marker(runtime_runs)
    if marker_errors:
        raise ValueError("; ".join(marker_errors))

    raw_path = runtime_runs / f"{run_id}.json"
    raw_meta_path = runtime_runs / f"{run_id}.json.apcf-meta.yaml"
    summary_path = runtime_runs / f"{run_id}.summary.json"
    summary_meta_path = runtime_runs / f"{run_id}.summary.json.apcf-meta.yaml"
    destinations = (raw_path, raw_meta_path, summary_path, summary_meta_path)
    if any(path.exists() or path.is_symlink() for path in destinations):
        raise FileExistsError("selfcheck run ID already exists; no file was overwritten")

    raw_data = (json.dumps(rows, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    mismatches = sum(
        1 for row in rows
        if "expected_exit_code" in row and row.get("exit_code") != row["expected_exit_code"]
    )
    summary = {
        "schema": 1,
        "run_id": run_id,
        "completed_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "run_outcome": run_outcome,
        "raw_path": raw_path.name,
        "raw_sha256": _sha256(raw_data),
        "raw_bytes": len(raw_data),
        "total_records": len(rows),
        "recorded_exit_codes": dict(sorted(Counter(str(row.get("exit_code")) for row in rows).items())),
        "expected_exit_code_mismatches": mismatches,
        "historical_log_recovered": False,
    }
    summary_data = (json.dumps(summary, ensure_ascii=False, indent=2) + "\n").encode("utf-8")

    created = []
    try:
        for path, payload in (
            (raw_path, raw_data),
            (raw_meta_path, _sidecar_bytes(raw_path.name, raw_data)),
            (summary_path, summary_data),
            (summary_meta_path, _sidecar_bytes(summary_path.name, summary_data)),
        ):
            _write_new(path, payload)
            created.append(path)
    except BaseException:
        for path in reversed(created):
            path.unlink(missing_ok=True)
        raise
    return summary


def _sidecar_errors(path: Path, object_name: str, payload: bytes) -> list[str]:
    if path.is_symlink() or not path.is_file():
        return [f"metadata sidecar missing or unsafe: {path.name}"]
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0].removeprefix("# APCF-META "))
    except (OSError, UnicodeError, IndexError, json.JSONDecodeError):
        return [f"metadata sidecar unreadable: {path.name}"]
    expected = [
        "schema: 1",
        "visibility: private",
        "kind: file",
        f"path: {object_name}",
        f"sha256: {_sha256(payload)}",
    ]
    if (not isinstance(header, dict) or type(header.get("schema")) is not int or header.get("schema") != 1 or
            header.get("visibility") != "private" or set(header) != {"schema", "visibility"} or
            lines[1:] != expected):
        return [f"metadata sidecar identity or SHA mismatch: {path.name}"]
    return []


def validate_summary_reference(summary_path: Path, runtime_runs: Path) -> tuple[set[Path], list[str]]:
    """Validate one summary and return its protected four-file evidence chain."""
    runtime_runs = Path(runtime_runs)
    summary_path = Path(summary_path)
    protected: set[Path] = set()
    errors = _private_runs_marker(runtime_runs)
    if runtime_runs.is_symlink() or not runtime_runs.is_dir():
        return protected, ["runtime/runs directory missing or unsafe"]
    if summary_path.is_symlink() or not summary_path.is_file():
        return protected, errors + ["summary missing or unsafe"]
    try:
        summary_path = summary_path.resolve(strict=True)
        summary_path.relative_to(runtime_runs.resolve(strict=True))
    except (OSError, ValueError):
        return protected, errors + ["summary path escapes runtime/runs"]
    try:
        summary_data = summary_path.read_bytes()
        summary = json.loads(summary_data.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return protected, errors + [f"summary unreadable: {summary_path.name}"]
    if not isinstance(summary, dict) or summary.get("schema") != 1:
        return protected, errors + [f"summary schema invalid: {summary_path.name}"]

    run_id = summary.get("run_id")
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        return protected, errors + [f"summary run ID invalid: {summary_path.name}"]
    if summary_path.name != f"{run_id}.summary.json":
        errors.append(f"summary filename does not match run ID: {summary_path.name}")
    if summary.get("run_outcome") not in {"PASS", "FAIL", "BLOCKED", "UNKNOWN"}:
        errors.append(f"summary outcome invalid: {summary_path.name}")

    expected_raw_name = f"{run_id}.json"
    raw_name = summary.get("raw_path")
    if raw_name != expected_raw_name or Path(str(raw_name)).name != raw_name or "\\" in str(raw_name):
        return protected, errors + [f"summary raw path is not the run's exact basename: {summary_path.name}"]

    raw_path = runtime_runs / expected_raw_name
    raw_meta_path = runtime_runs / f"{expected_raw_name}.apcf-meta.yaml"
    summary_meta_path = runtime_runs / f"{summary_path.name}.apcf-meta.yaml"
    protected.update(path.resolve(strict=False) for path in (raw_path, raw_meta_path, summary_path, summary_meta_path))
    if raw_path.is_symlink() or not raw_path.is_file():
        errors.append(f"referenced raw log missing or unsafe: {expected_raw_name}")
    else:
        try:
            raw_data = raw_path.read_bytes()
        except OSError:
            errors.append(f"referenced raw log unreadable: {expected_raw_name}")
        else:
            if summary.get("raw_sha256") != _sha256(raw_data) or summary.get("raw_bytes") != len(raw_data):
                errors.append(f"referenced raw log SHA or byte count mismatch: {expected_raw_name}")
            errors.extend(_sidecar_errors(raw_meta_path, expected_raw_name, raw_data))
    errors.extend(_sidecar_errors(summary_meta_path, summary_path.name, summary_data))
    return protected, errors


def validate_runlog_references(runtime_runs: Path) -> tuple[set[Path], list[str]]:
    """Protect every complete log chain and block cleanup on missing or orphaned links."""
    runtime_runs = Path(runtime_runs)
    if runtime_runs.is_symlink() or not runtime_runs.is_dir():
        return set(), ["runtime/runs directory missing or unsafe"]
    protected: set[Path] = set()
    errors = _private_runs_marker(runtime_runs)
    summaries = sorted(runtime_runs.glob("selfcheck-*.summary.json"))
    expected_paths: set[Path] = set()
    for summary_path in summaries:
        paths, issues = validate_summary_reference(summary_path, runtime_runs)
        protected.update(paths)
        expected_paths.update(paths)
        errors.extend(issues)
    for path in runtime_runs.iterdir():
        if path.name.startswith("selfcheck-") and path.resolve(strict=False) not in expected_paths:
            errors.append(f"orphan or unindexed selfcheck artifact blocks cleanup: {path.name}")
    return protected, errors
