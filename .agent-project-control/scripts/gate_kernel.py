# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import hashlib
import json
import os
import time
import tomllib
from datetime import datetime
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = ROOT / ".agent-project-control"
GATE_CONTRACT = FRAMEWORK_ROOT / "gate.toml"
GATE_SCHEMA = 1

RESULT_PASS = "PASS"
RESULT_REPAIR = "REPAIR_REQUIRED"
RESULT_BLOCKED = "BLOCKED"
RESULT_NO_PROGRESS = "NO_PROGRESS"
VALID_RESULTS = {RESULT_PASS, RESULT_REPAIR, RESULT_BLOCKED, RESULT_NO_PROGRESS}

EXIT_INVALID = 2


class GateError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def stable_hash(value: object) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def posix_rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def load_gate_contract() -> dict:
    try:
        data = tomllib.loads(GATE_CONTRACT.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise GateError(f"gate contract unreadable: {exc}") from exc
    if data.get("schema") != GATE_SCHEMA:
        raise GateError("gate contract schema mismatch")
    for key in ("attempts_relpath", "latest_relpath", "default_gate_id"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            raise GateError(f"gate contract missing {key}")
    codes = data.get("exit_codes")
    if not isinstance(codes, dict):
        raise GateError("gate contract missing exit_codes")
    expected = {RESULT_PASS: 0, "INVALID": 2, RESULT_REPAIR: 3, RESULT_BLOCKED: 4, RESULT_NO_PROGRESS: 5}
    for key, value in expected.items():
        if codes.get(key) != value:
            raise GateError(f"gate exit code drift: {key}")
    convergence = data.get("convergence")
    if not isinstance(convergence, dict):
        raise GateError("gate contract missing convergence")
    if convergence.get("cycle_scope") != "since-last-pass":
        raise GateError("unsupported gate cycle_scope")
    return data


def validate_turn_dir(turn_dir_raw: str | Path) -> Path:
    turn_dir = Path(turn_dir_raw)
    if not turn_dir.is_absolute():
        turn_dir = ROOT / turn_dir
    turn_dir = turn_dir.resolve()
    try:
        turn_dir.relative_to((FRAMEWORK_ROOT / "iterations").resolve())
    except ValueError as exc:
        raise GateError("gate turn-dir must be inside .agent-project-control/iterations") from exc
    if not turn_dir.is_dir():
        raise GateError("gate turn-dir does not exist")
    if not turn_dir.name.startswith("TR-"):
        raise GateError("gate turn-dir is not a TR directory")
    evidence = turn_dir / "evidence"
    request = turn_dir / "REQUEST.md"
    if not evidence.is_dir() or not request.is_file():
        raise GateError("gate turn-dir is missing REQUEST.md or evidence/")
    return turn_dir


def _evidence_path(turn_dir: Path, relpath: str) -> Path:
    path = (turn_dir / relpath).resolve(strict=False)
    evidence = (turn_dir / "evidence").resolve()
    try:
        path.relative_to(evidence)
    except ValueError as exc:
        raise GateError(f"gate evidence path escapes current TR evidence/: {relpath}") from exc
    if path.parent != evidence:
        raise GateError(f"gate evidence file must live directly under current TR evidence/: {relpath}")
    return path


def gate_paths(turn_dir: Path, contract: dict) -> tuple[Path, Path]:
    return (
        _evidence_path(turn_dir, contract["attempts_relpath"]),
        _evidence_path(turn_dir, contract["latest_relpath"]),
    )


def finding_id(finding: dict) -> str:
    identity = {
        "source": finding["source"],
        "code": finding["code"],
        "subject": finding["subject"],
        "scope": sorted(finding.get("scope", [])),
    }
    return "GF-" + stable_hash(identity)[:20]


def repair_id(repair: dict) -> str:
    identity = {
        "kind": repair["kind"],
        "target": repair["target"],
        "scope": sorted(repair.get("scope", [])),
    }
    return "GR-" + stable_hash(identity)[:20]


def normalize_findings(findings: Iterable[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for raw in findings:
        if not isinstance(raw, dict):
            raise GateError("gate finding is not an object")
        finding = dict(raw)
        for key in ("source", "code", "subject", "message", "repairability"):
            if not isinstance(finding.get(key), str) or not finding[key].strip():
                raise GateError(f"gate finding missing {key}")
        if finding["repairability"] not in {"repairable", "blocked"}:
            raise GateError("gate finding repairability must be repairable or blocked")
        scope = finding.get("scope", [])
        if not isinstance(scope, list) or any(not isinstance(x, str) for x in scope):
            raise GateError("gate finding scope must be a string list")
        finding["scope"] = sorted(set(scope))
        evidence = finding.get("evidence", [])
        if not isinstance(evidence, list):
            raise GateError("gate finding evidence must be a list")
        finding["evidence"] = evidence
        repair = finding.get("repair")
        if finding["repairability"] == "repairable":
            if not isinstance(repair, dict):
                raise GateError("repairable gate finding requires repair object")
            for key in ("kind", "target", "instruction", "verification"):
                if not isinstance(repair.get(key), str) or not repair[key].strip():
                    raise GateError(f"gate repair missing {key}")
            rscope = repair.get("scope", [])
            if not isinstance(rscope, list) or any(not isinstance(x, str) for x in rscope):
                raise GateError("gate repair scope must be a string list")
            repair = dict(repair)
            repair["scope"] = sorted(set(rscope))
            repair["repair_id"] = repair_id(repair)
            finding["repair"] = repair
        elif repair is not None:
            raise GateError("blocked gate finding must not expose an automatic repair")

        fid = finding_id(finding)
        finding["finding_id"] = fid
        if fid in seen:
            continue
        seen.add(fid)
        normalized.append(finding)
    normalized.sort(key=lambda f: f["finding_id"])
    return normalized


def build_repair_set(findings: list[dict]) -> list[dict]:
    repairs: dict[str, dict] = {}
    for finding in findings:
        repair = finding.get("repair")
        if not repair:
            continue
        rid = repair["repair_id"]
        if rid not in repairs:
            repairs[rid] = {
                **repair,
                "finding_ids": [finding["finding_id"]],
            }
        else:
            repairs[rid]["finding_ids"].append(finding["finding_id"])
    result = list(repairs.values())
    for repair in result:
        repair["finding_ids"] = sorted(set(repair["finding_ids"]))
    result.sort(key=lambda r: r["repair_id"])
    return result


def failure_fingerprint(findings: list[dict]) -> str:
    return stable_hash([f["finding_id"] for f in findings])


def repair_fingerprint(repairs: list[dict]) -> str:
    return stable_hash([r["repair_id"] for r in repairs])


def candidate_fingerprint(candidate_snapshot: dict) -> str:
    if not isinstance(candidate_snapshot, dict):
        raise GateError("candidate snapshot must be an object")
    return stable_hash(candidate_snapshot)


def _validate_history_row(row: dict, turn_rel: str, previous_hash: str | None, lineno: int) -> str:
    if not isinstance(row, dict) or row.get("schema") != GATE_SCHEMA:
        raise GateError(f"gate history has unsupported row at line {lineno}")
    if row.get("turn") != turn_rel:
        raise GateError(f"gate history line {lineno} belongs to a different Turn")
    if row.get("result") not in VALID_RESULTS:
        raise GateError(f"gate history line {lineno} has invalid result")
    if row.get("previous_attempt_hash") != previous_hash:
        raise GateError(f"gate history chain mismatch at line {lineno}")
    attempt_hash = row.get("attempt_hash")
    if not isinstance(attempt_hash, str) or len(attempt_hash) != 64:
        raise GateError(f"gate history line {lineno} missing attempt_hash")
    unsigned = dict(row)
    unsigned.pop("attempt_hash", None)
    expected = stable_hash(unsigned)
    if expected != attempt_hash:
        raise GateError(f"gate history tamper/corruption detected at line {lineno}")
    return attempt_hash


def load_history(path: Path, turn_rel: str) -> list[dict]:
    if not path.exists():
        return []
    if not path.is_file():
        raise GateError("gate-attempts.jsonl exists but is not a file")
    data = path.read_bytes()
    if data and not data.endswith(b"\n"):
        raise GateError("gate-attempts.jsonl has a partial final line")
    rows: list[dict] = []
    previous_hash: str | None = None
    for lineno, raw in enumerate(data.splitlines(), start=1):
        if not raw.strip():
            raise GateError(f"gate-attempts.jsonl has blank line {lineno}")
        try:
            row = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GateError(f"gate-attempts.jsonl invalid JSON at line {lineno}") from exc
        previous_hash = _validate_history_row(row, turn_rel, previous_hash, lineno)
        rows.append(row)
    return rows


def _append_jsonl(path: Path, record: dict) -> None:
    payload = canonical_json(record) + b"\n"
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        total = 0
        while total < len(payload):
            written = os.write(fd, payload[total:])
            if written <= 0:
                raise GateError("short write while appending gate-attempts.jsonl")
            total += written
        os.fsync(fd)
    finally:
        os.close(fd)


def _write_atomic(path: Path, payload: bytes) -> None:
    tmp = path.with_name(f".{path.name}.tmp-{os.getpid()}-{time.time_ns()}")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        total = 0
        while total < len(payload):
            written = os.write(fd, payload[total:])
            if written <= 0:
                raise GateError(f"short write while creating {path.name}")
            total += written
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, path)


def _repair_episode(history: list[dict], gate_id: str) -> list[dict]:
    relevant = [row for row in history if row.get("gate_id") == gate_id]
    last_pass = -1
    for idx, row in enumerate(relevant):
        if row.get("result") == RESULT_PASS:
            last_pass = idx
    return relevant[last_pass + 1 :]


def classify_transition(history: list[dict], gate_id: str, findings: list[dict], candidate_fp: str) -> dict:
    current_ids = {f["finding_id"] for f in findings}
    current_failure_fp = failure_fingerprint(findings)
    episode = _repair_episode(history, gate_id)
    if not episode:
        return {
            "kind": "INITIAL",
            "previous_attempt_id": None,
            "removed_findings": [],
            "added_findings": sorted(current_ids),
            "no_progress_reason": None,
        }

    previous = episode[-1]
    previous_ids = set(previous.get("finding_ids", []))
    removed = sorted(previous_ids - current_ids)
    added = sorted(current_ids - previous_ids)

    if current_failure_fp == previous.get("failure_fingerprint"):
        reason = (
            "identical-candidate-and-failure-set"
            if candidate_fp == previous.get("candidate_fingerprint")
            else "candidate-changed-but-failure-set-unchanged"
        )
        return {
            "kind": "STALLED",
            "previous_attempt_id": previous.get("attempt_id"),
            "removed_findings": removed,
            "added_findings": added,
            "no_progress_reason": reason,
        }

    prior_fps = {row.get("failure_fingerprint") for row in episode[:-1]}
    if current_failure_fp in prior_fps:
        return {
            "kind": "CYCLE",
            "previous_attempt_id": previous.get("attempt_id"),
            "removed_findings": removed,
            "added_findings": added,
            "no_progress_reason": "failure-set-reappeared-within-current-repair-episode",
        }

    if removed and not added:
        kind = "IMPROVED"
    elif removed and added and not (previous_ids & current_ids):
        kind = "CHANGED"
    elif removed and added:
        kind = "MIXED"
    elif added and not removed:
        kind = "REGRESSED"
    else:
        kind = "CHANGED"
    return {
        "kind": kind,
        "previous_attempt_id": previous.get("attempt_id"),
        "removed_findings": removed,
        "added_findings": added,
        "no_progress_reason": None,
    }


def evaluate_gate(
    *,
    turn_dir_raw: str | Path,
    gate_id: str,
    candidate_snapshot: dict,
    findings: Iterable[dict],
    adapter: str,
    adapter_evidence: list[dict] | None = None,
) -> tuple[int, dict]:
    contract = load_gate_contract()
    turn_dir = validate_turn_dir(turn_dir_raw)
    attempts_path, latest_path = gate_paths(turn_dir, contract)
    turn_rel = posix_rel(turn_dir)
    history = load_history(attempts_path, turn_rel)

    normalized = normalize_findings(findings)
    repairs = build_repair_set(normalized)
    candidate_fp = candidate_fingerprint(candidate_snapshot)
    failure_fp = failure_fingerprint(normalized)
    repairs_fp = repair_fingerprint(repairs)

    blocked = any(f["repairability"] == "blocked" for f in normalized)
    transition = classify_transition(history, gate_id, normalized, candidate_fp) if normalized else {
        "kind": "PASS",
        "previous_attempt_id": history[-1].get("attempt_id") if history else None,
        "removed_findings": sorted(set(history[-1].get("finding_ids", []))) if history else [],
        "added_findings": [],
        "no_progress_reason": None,
    }

    if not normalized:
        result = RESULT_PASS
    elif blocked:
        result = RESULT_BLOCKED
    elif transition["kind"] in {"STALLED", "CYCLE"}:
        result = RESULT_NO_PROGRESS
    else:
        result = RESULT_REPAIR

    exit_code = contract["exit_codes"][result]
    previous_hash = history[-1]["attempt_hash"] if history else None
    created_at = datetime.now().astimezone().isoformat(timespec="seconds")
    seed = {
        "gate_id": gate_id,
        "candidate_fingerprint": candidate_fp,
        "failure_fingerprint": failure_fp,
        "created_at": created_at,
        "nonce": time.time_ns(),
    }
    attempt_id = "GA-" + stable_hash(seed)[:20]

    record = {
        "schema": GATE_SCHEMA,
        "attempt_id": attempt_id,
        "gate_id": gate_id,
        "turn": turn_rel,
        "result": result,
        "exit_code": exit_code,
        "candidate_fingerprint": candidate_fp,
        "failure_fingerprint": failure_fp,
        "repair_fingerprint": repairs_fp,
        "finding_ids": [f["finding_id"] for f in normalized],
        "repair_ids": [r["repair_id"] for r in repairs],
        "findings": normalized,
        "repair_set": repairs,
        "transition": transition,
        "adapter": adapter,
        "adapter_evidence": adapter_evidence or [],
        "previous_attempt_hash": previous_hash,
        "created_at": created_at,
    }
    record["attempt_hash"] = stable_hash(record)

    # Revalidate existing history immediately before append; corruption must never be
    # overwritten by a new apparently-valid attempt.
    load_history(attempts_path, turn_rel)
    _append_jsonl(attempts_path, record)
    _write_atomic(latest_path, json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    return exit_code, record
