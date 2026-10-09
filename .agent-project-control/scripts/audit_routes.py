# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
import tomllib
from argparse import Namespace
from pathlib import Path, PurePosixPath

from route_context import (
    RouteError,
    agents_chain,
    build_route,
    capability_closure,
    load_contract,
    matching_capabilities,
    posix_rel,
    resolve_inside_repo,
    unresolved_sources,
)
from routing_activity import (
    ACTIVITY_SCHEMA,
    ActivityError,
    audit_paths,
    collect_activity,
    load_audit_contract,
    semantic_review,
)
from routing_receipt import (
    ReceiptError,
    load_records,
    load_receipt_contract,
    receipt_path,
    validate_turn_dir,
    verify_record,
)

ROOT = Path(__file__).resolve().parents[2]
EXIT_INVALID = 2
EXIT_GAP = 3
EXIT_UNRESOLVED = 4


def _matches_any(rel: str, patterns: list[str]) -> bool:
    p = PurePosixPath(rel)
    return any(fnmatch.fnmatchcase(rel, pat) or p.match(pat) for pat in patterns)


def _turn_rel(turn_dir: Path, name: str) -> str:
    return (turn_dir / name).resolve().relative_to(ROOT.resolve()).as_posix()


def classify_activity(turn_dir: Path, contract: dict, activity: dict) -> dict:
    audit = contract["audit"]
    neutral_globs = list(audit.get("route_neutral_globs", []))
    framework_globs = list(audit.get("framework_globs", []))

    current_turn_internal = {
        _turn_rel(turn_dir, "REQUEST.md"),
        _turn_rel(turn_dir, "CHECKLIST.md"),
        _turn_rel(turn_dir, "TEST.md"),
        _turn_rel(turn_dir, "TURN.md"),
    }
    evidence_prefix = (turn_dir / "evidence").resolve().relative_to(ROOT.resolve()).as_posix() + "/"

    facts: list[dict] = []
    target_paths: list[str] = []
    required_phases: set[str] = {"bootstrap"}
    required_capabilities: set[str] = set()
    unresolved: list[str] = []

    changed_paths = list(activity.get("changed_paths", []))
    for rel in changed_paths:
        if rel in current_turn_internal or rel.startswith(evidence_prefix):
            facts.append({"kind": "path-change", "subject": rel, "disposition": "neutral", "reason": "current-turn-control"})
            continue
        if _matches_any(rel, neutral_globs):
            facts.append({"kind": "path-change", "subject": rel, "disposition": "neutral", "reason": "configured-route-neutral"})
            continue

        required_phases.add("scope")
        target_paths.append(rel)
        mapped = ["phase:scope"]
        if _matches_any(rel, framework_globs):
            required_phases.add("framework")
            mapped.append("phase:framework")
        facts.append({"kind": "path-change", "subject": rel, "disposition": "mapped", "mapped_to": mapped})

    turn_changes = set(activity.get("turn_file_changes", []))
    for name in sorted(turn_changes):
        if name == "REQUEST.md":
            # collect_activity normally rejects this through baseline request SHA,
            # but retain an explicit invariant if the collector ever changes.
            unresolved.append("REQUEST.md changed after baseline")
            facts.append({"kind": "turn-file-change", "subject": name, "disposition": "unresolved"})
        elif name == "CHECKLIST.md":
            required_phases.add("scope")
            facts.append({"kind": "turn-file-change", "subject": name, "disposition": "mapped", "mapped_to": ["phase:scope"]})
        elif name == "TEST.md":
            required_phases.add("verification")
            facts.append({"kind": "turn-file-change", "subject": name, "disposition": "mapped", "mapped_to": ["phase:verification"]})
        elif name == "TURN.md":
            required_phases.add("finalization")
            facts.append({"kind": "turn-file-change", "subject": name, "disposition": "mapped", "mapped_to": ["phase:finalization"]})
        else:
            unresolved.append(f"unknown Turn control file changed: {name}")
            facts.append({"kind": "turn-file-change", "subject": name, "disposition": "unresolved"})

    if activity.get("git_head_changed"):
        required_phases.add("delivery")
        facts.append({
            "kind": "git-head-change",
            "subject": f"{activity['baseline']['git_head']} -> {activity['current_git_head']}",
            "disposition": "mapped",
            "mapped_to": ["phase:delivery"],
        })

    for pa in activity.get("new_parallel_units", []):
        required_phases.add("tools")
        facts.append({"kind": "parallel-agent", "subject": pa, "disposition": "mapped", "mapped_to": ["phase:tools"]})

    for event in activity.get("events", []):
        mapped: list[str] = []
        for phase in event.get("phases", []):
            required_phases.add(phase)
            mapped.append(f"phase:{phase}")
        for cap in event.get("capabilities", []):
            required_capabilities.add(cap)
            mapped.append(f"capability:{cap}")
        facts.append({
            "kind": "activity-event",
            "subject": event.get("kind"),
            "event_id": event.get("event_id"),
            "disposition": "mapped" if mapped else "neutral",
            "mapped_to": mapped,
        })

    return {
        "facts": facts,
        "target_paths": sorted(set(target_paths)),
        "required_phases": required_phases,
        "required_capabilities": required_capabilities,
        "unresolved": unresolved,
    }


def required_route(
    contract: dict,
    classified: dict,
    explicit_phases: list[str],
    explicit_capabilities: list[str],
    semantic_reviewed: bool,
    semantic_unresolved: list[str],
    review_phases: list[str] | None = None,
    review_capabilities: list[str] | None = None,
) -> dict:
    phases = set(classified["required_phases"])
    phases.update(explicit_phases)
    phases.update(review_phases or [])
    capabilities = set(classified["required_capabilities"])
    capabilities.update(explicit_capabilities)
    capabilities.update(review_capabilities or [])

    target_objs = [resolve_inside_repo(p) for p in classified["target_paths"]]
    triggered, unmatched = matching_capabilities(contract, target_objs)
    capabilities.update(triggered)

    # An unmatched target is not silently treated as semantically complete.
    # Generic scope rules cover implementation work, but specialized capabilities
    # may still be hidden inside a neutral-looking filename.
    unresolved = list(classified["unresolved"])
    if unmatched and not semantic_reviewed:
        unresolved.append(
            "semantic review required for changed targets without deterministic capability trigger: "
            + ", ".join(sorted(unmatched))
        )
    unresolved.extend(semantic_unresolved)

    ordered_caps = capability_closure(contract, capabilities) if capabilities else []

    args = Namespace(
        phase=[p for p in contract.get("phases", {}) if p in phases],
        capability=list(capabilities),
        target=classified["target_paths"],
        scope=None,
        turn_dir=None,
    )
    sources, resolved_phases, resolved_caps, route_unmatched = build_route(args, contract)

    source_paths = {posix_rel(s.path) for s in sources}

    # Independently require every applicable nested AGENTS source for changed targets.
    # A root-scoped receipt cannot silently cover a deeper AGENTS.md.
    for target in target_objs:
        for path in agents_chain(target):
            source_paths.add(posix_rel(path))

    current_unresolved = unresolved_sources(sources, contract, resolved_caps)
    for cap in current_unresolved:
        unresolved.append(f"required capability entrypoint is currently unresolved: {cap}")

    return {
        "phases": sorted(phases),
        "capabilities": ordered_caps,
        "sources": sorted(source_paths),
        "unmatched_targets": sorted(set(route_unmatched)),
        "unresolved": sorted(set(unresolved)),
    }


def valid_receipt_coverage(turn_dir: Path, baseline_created_at: str) -> dict:
    contract = load_receipt_contract()
    path = receipt_path(turn_dir, contract)
    records = load_records(path)

    valid: list[dict] = []
    invalid: list[dict] = []
    phases: set[str] = set()
    capabilities: set[str] = set()
    sources: set[str] = set()

    for record in records:
        # Receipts from before the immutable activity baseline cannot prove this
        # Turn's current activity coverage.
        if str(record.get("created_at", "")) < str(baseline_created_at):
            invalid.append({"receipt_id": record.get("receipt_id"), "problems": ["receipt predates activity baseline"]})
            continue
        problems = verify_record(record, turn_dir)
        if problems:
            invalid.append({"receipt_id": record.get("receipt_id"), "problems": problems})
            continue
        valid.append(record)
        phases.update(record.get("phases", []))
        capabilities.update(record.get("resolved_capabilities", []))
        for row in record.get("sources", []):
            if isinstance(row, dict) and isinstance(row.get("path"), str):
                sources.add(row["path"])

    return {
        "valid_receipts": [r.get("receipt_id") for r in valid],
        "invalid_receipts": invalid,
        "phases": sorted(phases),
        "capabilities": sorted(capabilities),
        "sources": sorted(sources),
    }


def _write_report(turn_dir: Path, contract: dict, report: dict) -> Path:
    _, _, report_path = audit_paths(turn_dir, contract)
    payload = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8") + b"\n"
    tmp = report_path.with_name(f".{report_path.name}.tmp-{os.getpid()}")
    with tmp.open("wb") as fh:
        fh.write(payload)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, report_path)
    return report_path


def audit(
    turn_dir_raw: str,
    explicit_phases: list[str],
    explicit_capabilities: list[str],
    semantic_reviewed: bool,
    semantic_unresolved: list[str],
    write_report: bool,
    explicit_targets: list[str] | None = None,
) -> tuple[int, dict]:
    contract = load_audit_contract()
    route_contract = load_contract()
    if contract != route_contract:
        # Both loaders point to the same routing.toml. Divergence is an internal error.
        raise ActivityError("routing contract loaders disagree")

    turn_dir = validate_turn_dir(turn_dir_raw)
    activity = collect_activity(turn_dir)
    classified = classify_activity(turn_dir, contract, activity)
    if explicit_targets:
        classified['required_phases'].add('scope')
        classified['target_paths'] = sorted(set(classified['target_paths']) | {
            posix_rel(resolve_inside_repo(p)) for p in explicit_targets})
    targets = [resolve_inside_repo(p) for p in classified['target_paths']]
    _, unmatched = matching_capabilities(route_contract, targets)
    review_errors, review_phases, review_capabilities = semantic_review(turn_dir, unmatched)
    # --semantic-reviewed remains a compatibility hint, never proof. Concrete
    # current-object evidence supplies the review and can only add obligations.
    reviewed = not review_errors
    required = required_route(
        contract,
        classified,
        explicit_phases,
        explicit_capabilities,
        reviewed,
        list(semantic_unresolved),
        review_phases,
        review_capabilities,
    )
    satisfied = valid_receipt_coverage(turn_dir, activity["baseline"]["created_at"])

    gaps = {
        "phases": sorted(set(required["phases"]) - set(satisfied["phases"])),
        "capabilities": sorted(set(required["capabilities"]) - set(satisfied["capabilities"])),
        "sources": sorted(set(required["sources"]) - set(satisfied["sources"])),
    }

    # Complete-consumption invariant: every observed fact has exactly one disposition.
    facts = classified["facts"]
    bad_facts = [
        fact for fact in facts
        if fact.get("disposition") not in {"mapped", "neutral", "unresolved"}
    ]
    if bad_facts:
        raise ActivityError("internal audit error: observed facts were not completely consumed")

    unresolved = list(required["unresolved"])
    if any(fact.get("disposition") == "unresolved" for fact in facts):
        unresolved.append("one or more observed activity facts remain unresolved")
    unresolved = sorted(set(unresolved))

    if unresolved:
        result = "ROUTE_UNRESOLVED"
        code = EXIT_UNRESOLVED
    elif any(gaps.values()):
        result = "ROUTE_GAP"
        code = EXIT_GAP
    else:
        result = "COVERED"
        code = 0

    report = {
        "schema": ACTIVITY_SCHEMA,
        "result": result,
        "turn": posix_rel(turn_dir),
        "activity": {
            "git_head_changed": activity["git_head_changed"],
            "changed_paths": activity["changed_paths"],
            "turn_file_changes": activity["turn_file_changes"],
            "new_parallel_units": activity["new_parallel_units"],
            "event_ids": [e.get("event_id") for e in activity["events"]],
        },
        "facts": facts,
        "required": required,
        "satisfied": satisfied,
        "gaps": gaps,
        "unresolved": unresolved,
        "semantic_review": {
            "reviewed": reviewed,
            "legacy_hint": semantic_reviewed,
            "evidence_problems": review_errors,
            "explicit_capabilities": explicit_capabilities,
            "explicit_phases": explicit_phases,
            "unresolved_notes": semantic_unresolved,
        },
    }
    if write_report:
        path = _write_report(turn_dir, contract, report)
        report["report_path"] = posix_rel(path)
    return code, report


def main() -> int:
    ap = argparse.ArgumentParser(description="Audit actual Turn activity against valid APCF routing receipts")
    ap.add_argument("--turn-dir", required=True)
    ap.add_argument("--phase", action="append", default=[], help="Additive semantic phase requirement; repeatable")
    ap.add_argument("--capability", action="append", default=[], help="Additive semantic capability requirement; repeatable")
    ap.add_argument(
        "--semantic-reviewed",
        action="store_true",
        help="Confirm that unmatched changed targets were semantically reviewed; this can only add/accept, never remove deterministic routes",
    )
    ap.add_argument(
        "--unresolved",
        action="append",
        default=[],
        help="Record an unresolved semantic coverage concern; repeatable and always blocks COVERED",
    )
    ap.add_argument("--no-write-report", action="store_true")
    args = ap.parse_args()

    try:
        code, report = audit(
            args.turn_dir,
            list(args.phase),
            list(args.capability),
            bool(args.semantic_reviewed),
            list(args.unresolved),
            not args.no_write_report,
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
        if code == 0:
            print("COVERED: observed Turn activity is covered by currently valid routing receipts")
        elif code == EXIT_GAP:
            print("ROUTE_GAP: one or more required routes are missing from current valid receipts")
        else:
            print("ROUTE_UNRESOLVED: coverage cannot be safely classified as complete")
        return code
    except (ActivityError, ReceiptError, RouteError) as exc:
        print(f"FAIL: {exc}")
        if isinstance(exc, ActivityError) and exc.code == 3:
            return EXIT_UNRESOLVED
        return getattr(exc, "code", EXIT_INVALID)
    except (OSError, UnicodeError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
        print(f"FAIL: route audit I/O or parse error: {exc}")
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
