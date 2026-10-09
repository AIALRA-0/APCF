# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Iterable

from common import FRAMEWORK_ROOT, ROOT

RECEIPT_SCHEMA = 1
EXIT_INVALID = 2
EXIT_NOT_FOUND = 3


class ReceiptError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


def posix_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def routing_contract_path() -> Path:
    framework = FRAMEWORK_ROOT / "framework.yaml"
    text = framework.read_text(encoding="utf-8")
    match = re.search(r'^routing_contract:\s*["\']([^"\']+)["\']\s*$', text, re.MULTILINE)
    if not match:
        raise ReceiptError("routing_contract is missing from framework.yaml")
    path = (ROOT / match.group(1)).resolve(strict=False)
    try:
        path.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise ReceiptError("routing contract escapes repository") from exc
    if not path.is_file():
        raise ReceiptError(f"routing contract missing: {posix_rel(path)}")
    return path


def load_receipt_contract() -> dict:
    path = routing_contract_path()
    with path.open("rb") as fh:
        contract = tomllib.load(fh)
    receipt = contract.get("receipt")
    if not isinstance(receipt, dict):
        raise ReceiptError("receipt contract is missing from routing.toml")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise ReceiptError("unsupported routing receipt schema")
    relpath = receipt.get("relpath")
    if not isinstance(relpath, str) or not relpath.strip():
        raise ReceiptError("receipt.relpath is missing")
    return contract


def validate_turn_dir(raw: str | Path) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve(strict=False)
    try:
        rel = p.relative_to((FRAMEWORK_ROOT / "iterations").resolve())
    except ValueError as exc:
        raise ReceiptError(f"turn directory is outside iterations/: {raw}") from exc
    if not p.is_dir():
        raise ReceiptError(f"turn directory does not exist: {raw}")
    parts = rel.parts
    if len(parts) < 3 or not parts[0].startswith("IT-") or parts[1] != "turns" or not parts[2].startswith("TR-"):
        raise ReceiptError(f"path is not a main TR directory: {raw}")
    required = ["REQUEST.md", "CHECKLIST.md", "TEST.md", "TURN.md", "evidence"]
    missing = [name for name in required if not (p / name).exists()]
    if missing:
        raise ReceiptError(f"turn directory missing required objects: {missing}")
    evidence = p / "evidence"
    if not evidence.is_dir():
        raise ReceiptError("turn evidence path is not a directory")
    return p


def receipt_path(turn_dir: Path, contract: dict) -> Path:
    relpath = contract["receipt"]["relpath"]
    path = (turn_dir / relpath).resolve(strict=False)
    try:
        path.relative_to(turn_dir.resolve())
    except ValueError as exc:
        raise ReceiptError("receipt path escapes turn directory") from exc
    if path.parent != (turn_dir / "evidence").resolve():
        raise ReceiptError("receipt must remain directly under current TR evidence/")
    return path


def current_git_head() -> str | None:
    proc = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True, capture_output=True)
    if proc.returncode != 0:
        return None
    return proc.stdout.strip() or None


def authority_paths() -> list[Path]:
    return [
        FRAMEWORK_ROOT / "framework.yaml",
        routing_contract_path(),
        FRAMEWORK_ROOT / "rules" / "INDEX.md",
        FRAMEWORK_ROOT / "scripts" / "route_context.py",
        FRAMEWORK_ROOT / "scripts" / "routing_receipt.py",
    ]


def authority_snapshot() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in authority_paths():
        if not path.is_file():
            raise ReceiptError(f"routing authority source missing: {posix_rel(path)}")
        rows.append({"path": posix_rel(path), "sha256": sha256_file(path)})
    return rows


def source_snapshot(sources: Iterable[object]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source in sources:
        path = Path(getattr(source, "path")).resolve()
        if not path.is_file():
            raise ReceiptError(f"routed source disappeared before receipt: {posix_rel(path)}")
        rows.append(
            {
                "kind": str(getattr(source, "kind")),
                "label": str(getattr(source, "label")),
                "path": posix_rel(path),
                "sha256": sha256_file(path),
            }
        )
    return rows


def verify_snapshot_rows(rows: list[dict[str, str]], label: str) -> None:
    problems: list[str] = []
    for i, row in enumerate(rows):
        problems.extend(_check_hash_row(row, f"{label}[{i}]"))
    if problems:
        raise ReceiptError("routing sources changed during emit: " + " | ".join(problems))


def request_sha256(turn_dir: Path) -> str:
    return sha256_file(turn_dir / "REQUEST.md")


def _validate_existing_jsonl(path: Path) -> None:
    if not path.exists():
        return
    if not path.is_file():
        raise ReceiptError("routing receipt path exists but is not a file")
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise ReceiptError("routing receipt log has a partial final line")
    for lineno, line in enumerate(data.splitlines(), start=1):
        if not line.strip():
            raise ReceiptError(f"routing receipt log has blank line {lineno}")
        try:
            record = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ReceiptError(f"routing receipt log is invalid at line {lineno}") from exc
        if not isinstance(record, dict) or record.get("schema") != RECEIPT_SCHEMA:
            raise ReceiptError(f"routing receipt log has unsupported record at line {lineno}")


def append_record(path: Path, record: dict) -> None:
    _validate_existing_jsonl(path)
    payload = canonical_json(record) + b"\n"
    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(path, flags, 0o600)
    try:
        written = os.write(fd, payload)
        if written != len(payload):
            raise ReceiptError("routing receipt append was incomplete")
        os.fsync(fd)
    finally:
        os.close(fd)


def make_receipt_id(unsigned: dict) -> str:
    nonce = f"{time.time_ns()}".encode("ascii")
    digest = hashlib.sha256(canonical_json(unsigned) + b"|" + nonce).hexdigest()[:16]
    stamp = datetime.now().astimezone().strftime("%Y%m%dT%H%M%S%z")
    return f"RR-{stamp}-{digest}"


def record_route_receipt(
    *,
    turn_dir_raw: str | Path,
    phases: list[str],
    declared_capabilities: list[str],
    resolved_capabilities: list[str],
    targets: list[str],
    scope: str,
    unmatched_targets: list[str],
    sources: Iterable[object],
    source_rows: list[dict[str, str]] | None = None,
    authority_rows: list[dict[str, str]] | None = None,
) -> tuple[Path, dict]:
    contract = load_receipt_contract()
    turn_dir = validate_turn_dir(turn_dir_raw)
    source_rows = source_rows if source_rows is not None else source_snapshot(sources)
    authority_rows = authority_rows if authority_rows is not None else authority_snapshot()
    unsigned = {
        "schema": RECEIPT_SCHEMA,
        "status": "RESOLVED",
        "turn": posix_rel(turn_dir),
        "request_sha256": request_sha256(turn_dir),
        "phases": list(phases),
        "declared_capabilities": list(declared_capabilities),
        "resolved_capabilities": list(resolved_capabilities),
        "targets": list(targets),
        "scope": scope,
        "unmatched_targets": list(unmatched_targets),
        "sources": source_rows,
        "authority": authority_rows,
        "git_head": current_git_head(),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    unsigned["route_fingerprint"] = hashlib.sha256(canonical_json({
        "turn": unsigned["turn"],
        "request_sha256": unsigned["request_sha256"],
        "phases": unsigned["phases"],
        "declared_capabilities": unsigned["declared_capabilities"],
        "resolved_capabilities": unsigned["resolved_capabilities"],
        "targets": unsigned["targets"],
        "scope": unsigned["scope"],
        "unmatched_targets": unsigned["unmatched_targets"],
        "sources": unsigned["sources"],
        "authority": unsigned["authority"],
        "git_head": unsigned["git_head"],
    })).hexdigest()
    record = {"receipt_id": make_receipt_id(unsigned), **unsigned}
    path = receipt_path(turn_dir, contract)
    append_record(path, record)
    return path, record


def load_records(path: Path) -> list[dict]:
    _validate_existing_jsonl(path)
    if not path.exists():
        return []
    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        records.append(json.loads(line))
    return records


def _check_hash_row(row: dict, label: str) -> list[str]:
    problems: list[str] = []
    raw = row.get("path")
    expected = row.get("sha256")
    if not isinstance(raw, str) or not isinstance(expected, str):
        return [f"{label} has invalid path/hash fields"]
    path = (ROOT / raw).resolve(strict=False)
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        return [f"{label} escapes repository: {raw}"]
    if not path.is_file():
        return [f"{label} missing: {raw}"]
    actual = sha256_file(path)
    if actual != expected:
        problems.append(f"{label} changed: {raw}; receipt={expected}; current={actual}")
    return problems


def verify_record(record: dict, expected_turn: Path | None = None) -> list[str]:
    problems: list[str] = []
    if record.get("schema") != RECEIPT_SCHEMA:
        problems.append("receipt schema mismatch")
    if record.get("status") != "RESOLVED":
        problems.append("receipt status is not RESOLVED")
    turn_raw = record.get("turn")
    if not isinstance(turn_raw, str):
        problems.append("receipt turn is missing")
        return problems
    try:
        turn_dir = validate_turn_dir(turn_raw)
    except ReceiptError as exc:
        problems.append(str(exc))
        return problems
    if expected_turn is not None and turn_dir.resolve() != expected_turn.resolve():
        problems.append("receipt belongs to a different turn")
    expected_request = record.get("request_sha256")
    if not isinstance(expected_request, str) or request_sha256(turn_dir) != expected_request:
        problems.append("turn REQUEST.md changed since routing")
    for i, row in enumerate(record.get("sources", [])):
        if not isinstance(row, dict):
            problems.append(f"source[{i}] is not an object")
            continue
        problems.extend(_check_hash_row(row, f"source[{i}]"))
    for i, row in enumerate(record.get("authority", [])):
        if not isinstance(row, dict):
            problems.append(f"authority[{i}] is not an object")
            continue
        problems.extend(_check_hash_row(row, f"authority[{i}]"))
    recorded_paths = {row.get("path") for row in record.get("authority", []) if isinstance(row, dict)}
    current_paths = {posix_rel(path) for path in authority_paths()}
    if recorded_paths != current_paths:
        problems.append("routing authority set changed since receipt")
    return problems


def latest_matching(records: list[dict], phase: str | None) -> dict | None:
    for record in reversed(records):
        if phase is None or phase in record.get("phases", []):
            return record
    return None


def main() -> int:
    ap = argparse.ArgumentParser(description="Verify the latest APCF routing receipt for a Turn")
    ap.add_argument("--turn-dir", required=True)
    ap.add_argument("--phase", help="Require the latest receipt containing this phase")
    args = ap.parse_args()
    try:
        contract = load_receipt_contract()
        turn_dir = validate_turn_dir(args.turn_dir)
        path = receipt_path(turn_dir, contract)
        records = load_records(path)
        record = latest_matching(records, args.phase)
        if record is None:
            wanted = f" for phase {args.phase}" if args.phase else ""
            print(f"ROUTE_RECEIPT_NOT_FOUND: no routing receipt{wanted}")
            return EXIT_NOT_FOUND
        problems = verify_record(record, turn_dir)
        if problems:
            for problem in problems:
                print("FAIL:", problem)
            return EXIT_INVALID
        print(
            "PASS: routing receipt valid; "
            f"receipt_id={record['receipt_id']}; phases={','.join(record.get('phases', [])) or 'none'}"
        )
        return 0
    except ReceiptError as exc:
        print(f"FAIL: {exc}")
        return exc.code
    except (OSError, UnicodeError, tomllib.TOMLDecodeError, json.JSONDecodeError) as exc:
        print(f"FAIL: routing receipt I/O or parse error: {exc}")
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
