# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path

from gate_enforce import EnforcementError, enforce_entrypoint
from common import ROOT, meta_line, now_stamp
from report_contract import validate_report
from routing_receipt import (
    authority_snapshot,
    load_receipt_contract,
    receipt_path,
    sha256_file,
    validate_turn_dir,
)
from test_ledger import validate_file as validate_test_form
from state_integrity import validate as validate_state


TRANSACTION_NAME = "finalize-transaction.json"
TRANSACTION_SCHEMA = 1
STATUS_TOKEN = "**Status**：<FINALIZE_STATUS>"


class FinalizeError(RuntimeError):
    pass


def _read_optional(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def _sha256(payload: bytes | None) -> str | None:
    return hashlib.sha256(payload).hexdigest() if payload is not None else None


def _journal_paths(tr: Path) -> tuple[Path, Path]:
    journal = tr / "evidence" / TRANSACTION_NAME
    return journal, journal.with_name(journal.name + ".apcf-meta.yaml")


def _normalized_turn_sha256(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise FinalizeError("finalize transaction TURN is not valid UTF-8") from exc
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith("- **Status**：")]
    if len(matches) != 1:
        raise FinalizeError("finalize transaction TURN must contain one recognized status value")
    index = matches[0]
    if lines[index].rstrip("\r\n") not in ("- **Status**：IN_PROGRESS", "- **Status**：FINALIZED"):
        raise FinalizeError("finalize transaction TURN has an unsupported status value")
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    lines[index] = "- " + STATUS_TOKEN + ending
    normalized = "".join(lines).encode("utf-8")
    return _sha256(normalized) or ""


def _report_sha256(payload: bytes) -> str:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise FinalizeError("finalize transaction TURN is not valid UTF-8") from exc
    marker = "## 1.1. USER REPORT"
    if text.count(marker) != 1:
        raise FinalizeError("finalize transaction TURN report marker is missing or duplicated")
    report = text.split(marker, 1)[1].strip().encode("utf-8")
    return _sha256(report) or ""


def _finalized_turn(payload: bytes) -> bytes:
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise FinalizeError("finalize transaction TURN is not valid UTF-8") from exc
    lines = text.splitlines(keepends=True)
    matches = [i for i, line in enumerate(lines) if line.startswith("- **Status**：")]
    if len(matches) != 1 or lines[matches[0]].rstrip("\r\n") != "- **Status**：IN_PROGRESS":
        raise FinalizeError("finalize preimage must have one IN_PROGRESS status line")
    index = matches[0]
    ending = "\r\n" if lines[index].endswith("\r\n") else "\n" if lines[index].endswith("\n") else ""
    lines[index] = "- **Status**：FINALIZED" + ending
    return "".join(lines).encode("utf-8")


def _current_matches_turn(current: bytes | None, tr: Path, turn: bytes) -> bool:
    if current is None:
        return False
    try:
        current_text = current.decode("utf-8")
        turn_text = turn.decode("utf-8")
    except UnicodeError:
        return False
    source = re.search(r"(?m)^- \*\*Source TURN\*\*：`([^`]+)`$", current_text)
    if source is None or source.group(1) != tr.relative_to(ROOT).as_posix():
        return False
    marker = "## 1.1. 最新完整用户报告"
    if current_text.count(marker) != 1:
        return False
    if turn_text.count("## 1.1. USER REPORT") != 1:
        return False
    current_report = current_text.split(marker, 1)[1].strip()
    turn_report = turn_text.split("## 1.1. USER REPORT", 1)[1].strip()
    return current_report == turn_report


def _validate_journal_gate(tr: Path, record: dict) -> None:
    from gate_kernel import GateError, candidate_fingerprint, gate_paths, load_gate_contract, load_history

    gate = record["gate_attempt"]
    snapshot = record.get("candidate_snapshot")
    if not isinstance(snapshot, dict) or candidate_fingerprint(snapshot) != gate.get("candidate_fingerprint"):
        raise FinalizeError("finalize transaction candidate snapshot does not match its Gate fingerprint")
    turn_rel = tr.relative_to(ROOT).as_posix()
    turn_files = snapshot.get("turn_files")
    source_turn_files = record.get("source_hashes", {}).get("turn_files")
    preimage = record.get("preimage")
    if (snapshot.get("turn") != turn_rel or not isinstance(turn_files, dict)
            or source_turn_files != turn_files or not isinstance(preimage, dict)
            or turn_files.get("TURN.md") != preimage.get("turn_sha256")):
        raise FinalizeError("finalize transaction preimage does not match the Gate-bound Turn files")
    if gate.get("result") != "PASS" or not all(
        isinstance(gate.get(key), str) and gate[key]
        for key in ("gate_id", "attempt_id", "attempt_hash", "candidate_fingerprint")
    ):
        raise FinalizeError("finalize transaction does not bind a valid PASS Gate attempt")
    try:
        attempts_path, _ = gate_paths(tr, load_gate_contract())
        history = load_history(attempts_path, tr.relative_to(ROOT).as_posix())
    except GateError as exc:
        raise FinalizeError("finalize transaction Gate history is invalid: " + str(exc)) from exc
    matches = [row for row in history if row.get("attempt_id") == gate["attempt_id"]]
    if len(matches) != 1:
        raise FinalizeError("finalize transaction Gate attempt is absent or duplicated in history")
    attempt = matches[0]
    if any(attempt.get(key) != gate.get(key) for key in
           ("gate_id", "attempt_id", "attempt_hash", "candidate_fingerprint", "result")):
        raise FinalizeError("finalize transaction Gate attempt does not match the validated history row")


def _image(turn: bytes, current: bytes | None) -> dict:
    return {
        "turn_sha256": _sha256(turn),
        "current_sha256": _sha256(current),
        "normalized_turn_sha256": _normalized_turn_sha256(turn),
        "report_sha256": _report_sha256(turn),
    }


def _source_hashes(snapshot: dict) -> dict:
    return {
        "turn_files": snapshot["turn_files"],
        "evidence": snapshot["evidence"],
        "business_targets": {
            row["path"]: row["sha256"] for row in snapshot["business_targets"]
        },
        "route_receipts_sha256": snapshot["route_receipts_sha256"],
        "activity_inputs": snapshot["activity_inputs"],
        "routing_authority": {
            row["path"]: row["sha256"] for row in snapshot["routing_authority"]
        },
    }


def _private_meta(payload: bytes) -> bytes:
    digest = hashlib.sha256(payload).hexdigest()
    return (
        '# APCF-META {"schema":1,"visibility":"private"}\n'
        f"schema: 1\nvisibility: private\nsha256: {digest}\n"
    ).encode("utf-8")


def _write_journal(tr: Path, record: dict) -> tuple[Path, Path]:
    journal, meta = _journal_paths(tr)
    payload = (json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    _atomic_write(journal, payload)
    _atomic_write(meta, _private_meta(payload))
    return journal, meta


def _save_journal(tr: Path, record: dict) -> tuple[Path, Path]:
    return _write_journal(tr, record)


def _load_journal(tr: Path, journal: Path) -> dict:
    try:
        row = json.loads(journal.read_text(encoding="utf-8"))
        if row.get("schema") != TRANSACTION_SCHEMA or row.get("turn") != tr.relative_to(ROOT).as_posix():
            raise FinalizeError("interrupted finalize journal does not match this Turn")
        if row.get("result") not in {"PREPARED", "COMMITTED"}:
            raise FinalizeError("finalize transaction has an invalid result")
        if (not isinstance(row.get("gate_attempt"), dict)
                or not isinstance(row.get("source_hashes"), dict)
                or not isinstance(row.get("candidate_snapshot"), dict)):
            raise FinalizeError("finalize transaction is missing its Gate or source snapshot")
        if not isinstance(row.get("preimage"), dict) or not isinstance(row.get("postimage"), dict):
            raise FinalizeError("finalize transaction is missing preimage or postimage")
        return row
    except FinalizeError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        raise FinalizeError(f"interrupted finalize journal is invalid: {exc}") from exc


def _restore_one(path: Path, original: bytes | None, written: bytes | None) -> None:
    current = _read_optional(path)
    if current == original:
        return
    if written is None:
        raise FinalizeError(f"cannot roll back {path.name}: this transaction did not write it")
    if current != written:
        raise FinalizeError(f"cannot roll back {path.name}: it changed outside this finalize transaction")
    if original is None:
        path.unlink()
    else:
        _atomic_write(path, original)


def _restore(tr: Path, turn_before: bytes, current_before: bytes | None,
             turn_written: bytes | None = None, current_written: bytes | None = None) -> None:
    turn_path = tr / "TURN.md"
    current_path = ROOT / "CURRENT.md"
    # If failure happened before the intended bytes were assembled, any change
    # away from the originals is not ours to overwrite.
    _restore_one(turn_path, turn_before, turn_written if turn_written is not None else b"")
    _restore_one(current_path, current_before, current_written if current_written is not None else b"")


def _remove_journal(paths: tuple[Path, Path]) -> None:
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def _recover_interrupted(tr: Path) -> bool:
    journal_paths = _journal_paths(tr)
    journal, _ = journal_paths
    if not journal.exists():
        return False
    record = _load_journal(tr, journal)
    turn_path = tr / "TURN.md"
    current_path = ROOT / "CURRENT.md"
    current_turn = _read_optional(turn_path)
    current_current = _read_optional(current_path)
    _validate_journal_gate(tr, record)
    preimage = record["preimage"]
    postimage = record["postimage"]
    if (preimage.get("normalized_turn_sha256") != postimage.get("normalized_turn_sha256")
            or preimage.get("report_sha256") != postimage.get("report_sha256")):
        raise FinalizeError("finalize transaction changed content beyond the one status line")

    if record["result"] == "COMMITTED":
        if (current_turn is None or _image(current_turn, current_current) != postimage
                or not _current_matches_turn(current_current, tr, current_turn)):
            raise FinalizeError("committed finalize transaction no longer matches its postimage")
        expected_meta = _private_meta(journal.read_bytes())
        meta = journal_paths[1]
        if _read_optional(meta) != expected_meta:
            _atomic_write(meta, expected_meta)
        return False

    rollback = record.get("rollback")
    if not isinstance(rollback, dict):
        raise FinalizeError("prepared finalize transaction has no rollback image")
    try:
        turn_before = base64.b64decode(rollback["turn_base64"], validate=True)
        current_existed = rollback["current_existed"]
        if not isinstance(current_existed, bool):
            raise FinalizeError("prepared finalize transaction has invalid CURRENT rollback state")
        current_encoded = rollback.get("current_base64")
        if current_existed:
            if not isinstance(current_encoded, str):
                raise FinalizeError("prepared finalize transaction is missing CURRENT rollback bytes")
            current_before = base64.b64decode(current_encoded, validate=True)
        else:
            if current_encoded is not None:
                raise FinalizeError("prepared finalize transaction has inconsistent CURRENT rollback state")
            current_before = None
    except FinalizeError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise FinalizeError(f"prepared finalize transaction rollback image is invalid: {exc}") from exc

    if _image(turn_before, current_before) != preimage:
        raise FinalizeError("prepared finalize transaction rollback image does not match its preimage")
    expected_turn = _finalized_turn(turn_before)
    if _sha256(expected_turn) != postimage.get("turn_sha256"):
        raise FinalizeError("prepared finalize transaction postimage is not the unique status transition")
    if current_turn != turn_before and _sha256(current_turn) != record["postimage"].get("turn_sha256"):
        raise FinalizeError("interrupted finalize journal found, but TURN no longer matches its transaction")
    if current_current != current_before and _sha256(current_current) != record["postimage"].get("current_sha256"):
        raise FinalizeError("interrupted finalize journal found, but CURRENT no longer matches its transaction")
    if current_current != current_before and not _current_matches_turn(current_current, tr, expected_turn):
        raise FinalizeError("interrupted finalize CURRENT does not report the journal's finalized TURN")

    _atomic_write(turn_path, turn_before)
    if current_before is None:
        try:
            current_path.unlink()
        except FileNotFoundError:
            pass
    else:
        _atomic_write(current_path, current_before)
    _remove_journal(journal_paths)
    return True


def _candidate_guard_snapshot(tr: Path) -> dict:
    from routing_activity import collect_activity, evidence_snapshot, file_state, managed_targets, tr_file_hashes

    activity_contract = load_receipt_contract()
    route_log = receipt_path(tr, activity_contract)
    audit = activity_contract.get("audit", {})
    input_hashes = {}
    for name, relpath in (
        ("activity_baseline", audit.get("baseline_relpath")),
        ("activity_events", audit.get("events_relpath")),
    ):
        if isinstance(relpath, str):
            path = tr / relpath
            input_hashes[name] = sha256_file(path) if path.is_file() else None

    activity = collect_activity(tr)
    targets = managed_targets(tr)
    return {
        "turn_files": tr_file_hashes(tr),
        "evidence": evidence_snapshot(tr),
        "business_targets": [file_state(path) for path in targets],
        "activity_inputs": input_hashes,
        "activity_events": activity.get("events", []),
        "git_head": activity.get("current_git_head"),
        "git_head_changed": activity.get("git_head_changed"),
        "new_parallel_units": activity.get("new_parallel_units", []),
        "route_receipts_sha256": sha256_file(route_log) if route_log.is_file() else None,
        "routing_authority": authority_snapshot(),
    }


def _build_current(tr: Path, report: str) -> bytes:
    current = (
        "# 1. 当前状态\n\n"
        f"- **Latest TR**：`{tr.name.split('_', 1)[0]}`\n"
        f"- **Updated**：`{now_stamp()}`\n"
        f"- **Source TURN**：`{tr.relative_to(ROOT).as_posix()}`\n\n"
        "## 1.1. 最新完整用户报告\n\n" + report
    )
    return (meta_line("public") + "\n" + current.rstrip() + "\n").encode("utf-8")


def _write_if_unchanged(path: Path, original: bytes | None, payload: bytes) -> None:
    if _read_optional(path) != original:
        raise FinalizeError(f"{path.name} changed before finalize transaction write")
    _atomic_write(path, payload)


def _transactional_state_write(tr: Path, turn_before: bytes, current_before: bytes | None,
                               turn_after: bytes, current_after: bytes, guard_snapshot: dict,
                               gate_record: dict, candidate_snapshot: dict) -> list[str]:
    turn_path = tr / "TURN.md"
    current_path = ROOT / "CURRENT.md"
    journal_paths: tuple[Path, Path] | None = None
    record = {
        "schema": TRANSACTION_SCHEMA,
        "turn": tr.relative_to(ROOT).as_posix(),
        "result": "PREPARED",
        "gate_attempt": {
            "gate_id": gate_record.get("gate_id"),
            "attempt_id": gate_record.get("attempt_id"),
            "attempt_hash": gate_record.get("attempt_hash"),
            "candidate_fingerprint": gate_record.get("candidate_fingerprint"),
            "result": gate_record.get("result"),
        },
        "candidate_snapshot": candidate_snapshot,
        "source_hashes": _source_hashes(guard_snapshot),
        "preimage": _image(turn_before, current_before),
        "postimage": _image(turn_after, current_after),
        "rollback": {
            "turn_base64": base64.b64encode(turn_before).decode("ascii"),
            "current_existed": current_before is not None,
            "current_base64": base64.b64encode(current_before).decode("ascii") if current_before is not None else None,
        },
    }
    try:
        if record["gate_attempt"]["result"] != "PASS":
            raise FinalizeError("transaction can only follow a PASS Gate attempt")
        journal_paths = _save_journal(tr, record)
        _write_if_unchanged(turn_path, turn_before, turn_after)
        _write_if_unchanged(current_path, current_before, current_after)
        state_errors = validate_state(False)
        if state_errors:
            raise FinalizeError("state integrity failed after finalize writes: " + "; ".join(state_errors))
        record["result"] = "COMMITTED"
        record["rollback"] = None
        try:
            _write_journal(tr, record)
        except Exception:
            # The main journal rename is the commit point. Its metadata sidecar
            # is repairable on the next invocation, so do not roll back a state
            # whose durable COMMITTED record already matches both postimages.
            journal, _ = _journal_paths(tr)
            persisted = _load_journal(tr, journal) if journal.is_file() else None
            if (
                persisted == record
                and _image(_read_optional(turn_path) or b"", _read_optional(current_path)) == record["postimage"]
            ):
                return []
            raise
        return []
    except Exception as exc:
        try:
            _restore(tr, turn_before, current_before, turn_after, current_after)
        except Exception as rollback_exc:
            # Keep the journal for the next invocation to finish the recovery.
            return [f"{exc}; rollback needs recovery: {rollback_exc}"]
        if journal_paths is not None:
            if journal_paths[0].is_file():
                record["result"] = "PREPARED"
                record["rollback"] = {
                    "turn_base64": base64.b64encode(turn_before).decode("ascii"),
                    "current_existed": current_before is not None,
                    "current_base64": base64.b64encode(current_before).decode("ascii") if current_before is not None else None,
                }
                try:
                    _write_journal(tr, record)
                except Exception:
                    pass
            try:
                _remove_journal(journal_paths)
            except OSError as cleanup_exc:
                return [f"{exc}; rollback completed but journal cleanup failed: {cleanup_exc}"]
        else:
            _remove_journal(_journal_paths(tr))
        return [str(exc)]


def _finalize(tr: Path) -> int:
    if _recover_interrupted(tr):
        raise FinalizeError("interrupted finalize transaction was rolled back; review restored state before retrying")

    turn_path = tr / "TURN.md"
    current_path = ROOT / "CURRENT.md"
    turn_before = turn_path.read_bytes()
    current_before = _read_optional(current_path)
    try:
        text = turn_before.decode("utf-8")
    except UnicodeError as exc:
        raise FinalizeError("TURN.md is not valid UTF-8") from exc
    marker = "## 1.1. USER REPORT"
    if text.count(marker) != 1:
        raise FinalizeError("USER REPORT marker missing or duplicated")
    status_lines = [line for line in text.splitlines() if line.startswith("- **Status**：")]
    if status_lines != ["- **Status**：IN_PROGRESS"]:
        raise FinalizeError("Turn is not in a unique IN_PROGRESS state; finalize is immutable")
    report = text.split(marker, 1)[1].strip()
    if not report or report == "尚未收口":
        raise FinalizeError("USER REPORT empty")

    errors = ["TEST form: " + e for e in validate_test_form(tr / "TEST.md", tr / "CHECKLIST.md")]
    errors.extend(validate_report(report, tr))
    if errors:
        raise FinalizeError("; ".join(errors))

    before_gate: dict[str, dict] = {}

    def capture_pre_gate(candidate_turn: Path) -> None:
        from gate_check import _candidate_snapshot
        from gate_kernel import candidate_fingerprint

        if candidate_turn.resolve() != tr.resolve():
            raise FinalizeError("pre-Gate snapshot was requested for a different Turn")
        if turn_path.read_bytes() != turn_before or _read_optional(current_path) != current_before:
            raise FinalizeError("TURN.md or CURRENT.md changed before the Gate attempt")
        before_gate["snapshot"] = _candidate_guard_snapshot(tr)
        before_gate["candidate_snapshot"] = _candidate_snapshot(tr)
        before_gate["candidate_fingerprint"] = candidate_fingerprint(before_gate["candidate_snapshot"])

    code, gate_record = enforce_entrypoint(
        entrypoint="finalize",
        turn_dir_raw=tr,
        before_gate=capture_pre_gate,
    )
    if code:
        return code
    if not isinstance(gate_record, dict) or gate_record.get("result") != "PASS":
        raise FinalizeError("finalize Gate returned no verifiable PASS attempt")
    if "snapshot" not in before_gate:
        raise FinalizeError("pre-Gate snapshot was not captured")
    if gate_record.get("candidate_fingerprint") != before_gate.get("candidate_fingerprint"):
        raise FinalizeError("Gate evaluated a different candidate from the immutable pre-Gate snapshot")
    if turn_path.read_bytes() != turn_before or _read_optional(current_path) != current_before:
        raise FinalizeError("TURN.md or CURRENT.md changed during the Gate attempt")
    if _candidate_guard_snapshot(tr) != before_gate["snapshot"]:
        raise FinalizeError("business candidate, routing Receipt or evidence changed during the Gate attempt")

    turn_after = _finalized_turn(turn_before)
    current_after = _build_current(tr, report)
    if not _current_matches_turn(current_after, tr, turn_after):
        raise FinalizeError("generated CURRENT report does not match the finalized TURN")
    transaction_errors = _transactional_state_write(
        tr,
        turn_before,
        current_before,
        turn_after,
        current_after,
        before_gate["snapshot"],
        gate_record,
        before_gate["candidate_snapshot"],
    )
    if transaction_errors:
        for error in transaction_errors:
            print("FAIL:", error)
        return 2
    print("PASS")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("turn_dir")
    a = ap.parse_args()
    try:
        tr = validate_turn_dir(Path(a.turn_dir).resolve())
        return _finalize(tr)
    except Exception as exc:
        print(f"FAIL: {exc}")
        return getattr(exc, "code", 2)


if __name__ == "__main__":
    raise SystemExit(main())
