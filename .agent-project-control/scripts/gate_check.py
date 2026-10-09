# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from argparse import Namespace
from pathlib import Path, PurePosixPath

from audit_routes import EXIT_GAP, EXIT_UNRESOLVED, audit as route_audit
from gate_kernel import GateError, evaluate_gate, posix_rel, sha256_file, validate_turn_dir
from route_context import build_route, load_contract, resolve_inside_repo
from routing_activity import (ActivityError, acceptance_errors, audit_paths, collect_activity,
                              content_review_errors, evidence_snapshot, file_state,
                              load_audit_contract, tr_file_hashes, workflow_errors)
from routing_receipt import ReceiptError, load_receipt_contract, load_records, receipt_path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_GATE = "route-readiness"


VALID_ENFORCEMENT_CLASSES = {"integrity", "phase", "scope", "source", "capability", "semantic"}


def _load_profile(profile: str) -> set[str]:
    from gate_kernel import load_gate_contract
    contract = load_gate_contract()
    profiles = contract.get("profiles")
    if not isinstance(profiles, dict):
        raise GateError("gate contract missing profiles")
    spec = profiles.get(profile)
    if not isinstance(spec, dict):
        raise GateError(f"unknown gate profile: {profile}")
    classes = spec.get("enforce_classes")
    if not isinstance(classes, list) or not classes or any(not isinstance(x, str) for x in classes):
        raise GateError(f"gate profile {profile} has invalid enforce_classes")
    unknown = sorted(set(classes) - VALID_ENFORCEMENT_CLASSES)
    if unknown:
        raise GateError(f"gate profile {profile} has unknown enforcement classes: {unknown}")
    return set(classes)


def _profile_findings(findings: list[dict], profile: str) -> tuple[list[dict], list[dict]]:
    allowed = _load_profile(profile)
    enforced: list[dict] = []
    deferred: list[dict] = []
    for finding in findings:
        cls = finding.get("enforcement_class")
        if cls not in VALID_ENFORCEMENT_CLASSES:
            raise GateError(f"gate finding missing/invalid enforcement_class: {finding.get('code')}")
        (enforced if cls in allowed else deferred).append(finding)
    return enforced, deferred


def _matches_any(rel: str, patterns: list[str]) -> bool:
    p = PurePosixPath(rel)
    return any(fnmatch.fnmatchcase(rel, pat) or p.match(pat) for pat in patterns)


def _candidate_snapshot(turn_dir: Path) -> dict:
    activity = collect_activity(turn_dir)
    audit_contract = load_audit_contract()["audit"]
    neutral_globs = list(audit_contract.get("route_neutral_globs", []))
    turn_rel = posix_rel(turn_dir)
    evidence_prefix = turn_rel + "/evidence/"
    control_paths = {turn_rel + "/" + name for name in ("REQUEST.md", "CHECKLIST.md", "TEST.md", "TURN.md")}
    candidate_paths = [
        path for path in activity.get("changed_paths", [])
        if not path.startswith(evidence_prefix)
        and path not in control_paths
        and not _matches_any(path, neutral_globs)
    ]
    changed_rows = [file_state(path) for path in candidate_paths]
    current_turn_hashes = tr_file_hashes(turn_dir)
    events = [
        {
            "event_id": event.get("event_id"),
            "kind": event.get("kind"),
            "phases": event.get("phases", []),
            "capabilities": event.get("capabilities", []),
        }
        for event in activity.get("events", [])
    ]
    return {
        "turn": posix_rel(turn_dir),
        "baseline_created_at": activity["baseline"].get("created_at"),
        "request_sha256": activity["baseline"].get("request_sha256"),
        "git_head": activity.get("current_git_head"),
        "changed_rows": changed_rows,
        "turn_files": current_turn_hashes,
        "parallel_units": sorted(activity.get("new_parallel_units", [])),
        "events": events,
        "evidence_files": evidence_snapshot(turn_dir),
    }


def _markdown_prose(text: str) -> list[tuple[int, str]]:
    """Return editable prose positions, preserving code, raw quotes and identifiers."""
    result = []
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = re.match(r'^\s*(`{3,}|~{3,})', line)
        if match:
            token = match.group(1)
            if fence is None:
                fence = token[0]
            elif token[0] == fence:
                fence = None
            continue
        if fence or line.lstrip().startswith('>') or 'APCF-META' in line:
            continue
        # Inline code and literal excerpts are protected source objects.
        line = re.sub(r'(`+).*?\1', '', line)
        line = re.sub(r'“[^”]*”|「[^」]*」|『[^』]*』', '', line)
        result.append((number, line))
    return result


def _content_findings(turn_dir: Path, targets: list[str]) -> list[dict]:
    from route_context import capability_closure, matching_capabilities, resolve_inside_repo
    from terminology_review import has_user_report_candidate
    contract = load_contract()
    findings = []
    current_turn_report = turn_dir / 'TURN.md'
    if has_user_report_candidate(current_turn_report):
        # A non-placeholder USER REPORT candidate stays in the existing
        # Writing/Style content-review flow, including malformed reports that
        # must be rejected instead of silently dropping out of Gate scope.
        targets = list(targets) + [posix_rel(current_turn_report)]
    for target in sorted(set(targets)):
        path = ROOT / target
        if not path.is_file():
            # Deletion semantics are covered by the object-specific semantic review.
            continue
        caps, _ = matching_capabilities(contract, [resolve_inside_repo(target)])
        needed = [c for c in capability_closure(contract, caps) if c in {'writing', 'style', 'design', 'readme'}]
        if not needed:
            continue
        errors = content_review_errors(turn_dir, target, needed)
        if 'writing' in needed and path.suffix.lower() in {'.md', '.mdx', '.rst', '.adoc'}:
            # This deterministic subset is version-bound; semantic observations
            # remain necessary and are never inferred from a clean punctuation scan.
            from standards_contract import validate as validate_standards
            errors.extend('standards contract: ' + e for e in validate_standards())
            for number, prose in _markdown_prose(path.read_text(encoding='utf-8')):
                if '。' in prose and re.search(r'[\u3400-\u9fff]', prose):
                    errors.append(f'{target}:{number}: Writing v0.1 §1 editable Chinese full stop')
        if errors:
            findings.append(_finding(
                code='CONTENT_ACCEPTANCE_REQUIRED', subject=target,
                message='; '.join(errors), repairability='repairable', enforcement_class='semantic',
                scope=[target], evidence=[{'kind': 'current-content', 'path': target, 'sha256': sha256_file(path)}],
                repair=_repair('content-review', target, turn_dir,
                    'Read the applicable normative source, repair only editable content, execute relevant checks and record located observations for the current SHA.',
                    'Re-run the same full Gate; current content and current review source hashes must match.', [target])))
    return findings


def _obligation_findings(turn_dir: Path, errors: list[str], code: str, instruction: str) -> list[dict]:
    if not errors:
        return []
    return [_finding(code=code, subject=posix_rel(turn_dir), message='; '.join(errors),
                     repairability='repairable', enforcement_class='integrity',
                     evidence=[{'kind': 'current-obligation', 'problems': errors}],
                     repair=_repair(code.lower(), posix_rel(turn_dir), turn_dir, instruction,
                                    'Re-run this managed entrypoint against the same current candidate.'))]


def _repair(kind: str, target: str, turn_dir: Path, instruction: str, verification: str, scope: list[str] | None = None) -> dict:
    return {
        "kind": kind,
        "target": target,
        "scope": scope or [],
        "instruction": instruction,
        "verification": verification,
    }


def _finding(
    *,
    code: str,
    subject: str,
    message: str,
    repairability: str,
    enforcement_class: str,
    scope: list[str] | None = None,
    evidence: list[dict] | None = None,
    repair: dict | None = None,
) -> dict:
    return {
        "source": "post-route-audit",
        "code": code,
        "subject": subject,
        "scope": scope or [],
        "message": message,
        "repairability": repairability,
        "enforcement_class": enforcement_class,
        "evidence": evidence or [],
        "repair": repair,
    }


def _implied_sources(contract: dict, *, phase: str | None = None, capability: str | None = None) -> set[str]:
    args = Namespace(
        phase=[phase] if phase else [],
        capability=[capability] if capability else [],
        target=[],
        scope=None,
        turn_dir=None,
    )
    sources, _, _, _ = build_route(args, contract)
    return {posix_rel(source.path) for source in sources}


def _route_findings(report: dict, turn_dir: Path) -> list[dict]:
    findings: list[dict] = []
    gaps = report.get("gaps", {})
    phases = list(gaps.get("phases", []))
    capabilities = list(gaps.get("capabilities", []))
    source_gaps = set(gaps.get("sources", []))
    contract = load_contract()

    implied: set[str] = set()
    for phase in phases:
        implied |= _implied_sources(contract, phase=phase)
        findings.append(_finding(
            code="ROUTE_PHASE_GAP",
            enforcement_class="phase",
            subject=phase,
            message=f"Required route phase is not covered by a current valid receipt: {phase}",
            repairability="repairable",
            evidence=[{"kind": "route-audit", "gap": "phase", "value": phase}],
            repair=_repair(
                "route-phase",
                phase,
                turn_dir,
                f"Route phase '{phase}' for the current Turn, then re-run only the affected verification/audit path.",
                "Re-run gate_check.py for the same Turn; the phase and its implied sources must disappear from the gap set.",
            ),
        ))

    for capability in capabilities:
        implied |= _implied_sources(contract, capability=capability)
        findings.append(_finding(
            code="ROUTE_CAPABILITY_GAP",
            enforcement_class="capability",
            subject=capability,
            message=f"Required route capability is not covered by a current valid receipt: {capability}",
            repairability="repairable",
            evidence=[{"kind": "route-audit", "gap": "capability", "value": capability}],
            repair=_repair(
                "route-capability",
                capability,
                turn_dir,
                f"Route capability '{capability}' for the current Turn, then re-check only artifacts affected by that capability.",
                "Re-run gate_check.py for the same Turn; the capability and capability-owned source gaps must be gone.",
            ),
        ))

    for source in sorted(source_gaps - implied):
        path = Path(source)
        if path.name in {"AGENTS.md", "AGENTS.override.md"}:
            scope = path.parent.as_posix() if path.parent.as_posix() not in {"", "."} else "."
            findings.append(_finding(
                code="ROUTE_SCOPE_SOURCE_GAP",
                enforcement_class="scope",
                subject=source,
                message=f"A required scoped AGENTS source was not read by any current valid receipt: {source}",
                repairability="repairable",
                scope=[scope],
                evidence=[{"kind": "route-audit", "gap": "source", "value": source}],
                repair=_repair(
                    "route-scope",
                    scope,
                    turn_dir,
                    f"Re-route the current Turn with scope '{scope}' so the applicable AGENTS chain is actually read.",
                    "Re-run gate_check.py; this scoped AGENTS source must disappear from the source gap set.",
                    [scope],
                ),
            ))
        else:
            findings.append(_finding(
                code="ROUTE_SOURCE_GAP",
                enforcement_class="source",
                subject=source,
                message=f"A required route source is missing from current valid receipts: {source}",
                repairability="repairable",
                scope=[source],
                evidence=[{"kind": "route-audit", "gap": "source", "value": source}],
                repair=_repair(
                    "route-source",
                    source,
                    turn_dir,
                    f"Resolve which existing route owns '{source}', route that existing phase/capability/scope, and do not create a one-off bypass.",
                    "Re-run gate_check.py; the exact source gap must disappear without weakening routing.toml or Receipt validation.",
                    [source],
                ),
            ))

    for item in report.get("unresolved", []):
        text = str(item)
        if text.startswith("semantic review required for changed targets without deterministic capability trigger:"):
            targets = text.split(":", 1)[1].strip()
            scope = [x.strip() for x in targets.split(",") if x.strip()]
            findings.append(_finding(
                code="SEMANTIC_ROUTE_REVIEW_REQUIRED",
                enforcement_class="semantic",
                subject=targets,
                message=text,
                repairability="repairable",
                scope=scope,
                evidence=[{"kind": "route-audit", "unresolved": text}],
                repair=_repair(
                    "semantic-route-review",
                    targets,
                    turn_dir,
                    "Review only these unmatched changed targets for hidden specialized capabilities; add required phases/capabilities or explicitly confirm generic scope if none apply.",
                    "Re-run gate_check.py with the resulting semantic declarations; no unmatched semantic uncertainty may remain.",
                    scope,
                ),
            ))
        elif text.startswith("required capability entrypoint is currently unresolved:"):
            capability = text.rsplit(":", 1)[1].strip()
            findings.append(_finding(
                code="CAPABILITY_ENTRYPOINT_UNRESOLVED",
                enforcement_class="capability",
                subject=capability,
                message=text,
                repairability="blocked",
                evidence=[{"kind": "route-audit", "unresolved": text}],
            ))
        elif text == "one or more observed activity facts remain unresolved":
            # This summary line is subordinate to the concrete unresolved fact(s).
            continue
        else:
            findings.append(_finding(
                code="ROUTE_UNRESOLVED",
                enforcement_class="integrity",
                subject=text,
                message=text,
                repairability="blocked",
                evidence=[{"kind": "route-audit", "unresolved": text}],
            ))
    return findings


def _action_route_findings(turn_dir: Path, targets: list[str], report: dict) -> list[dict]:
    """An action needs pre-routing for its own targets, even under core.

    General core audit may defer professional obligations. This narrow execution
    prerequisite does not perform final content review or weaken that deferral.
    """
    contract = load_contract()
    valid = set(report.get('satisfied', {}).get('valid_receipts', []))
    records = [row for row in load_records(receipt_path(turn_dir, load_receipt_contract()))
               if row.get('receipt_id') in valid]
    findings = []
    for raw in sorted(set(targets)):
        target = posix_rel(resolve_inside_repo(raw))
        sources, _, caps, _ = build_route(Namespace(phase=['scope'], capability=[],
            target=[target], scope=None, turn_dir=None), contract)
        target_records = [row for row in records if target in row.get('targets', [])]
        covered_caps = {cap for row in target_records for cap in row.get('resolved_capabilities', [])}
        covered_sources = {source['path'] for row in target_records for source in row.get('sources', [])}
        missing_caps = sorted(set(caps) - covered_caps)
        missing_sources = sorted({posix_rel(source.path) for source in sources} - covered_sources)
        if not target_records or missing_caps or missing_sources:
            findings.append(_finding(code='ACTION_TARGET_ROUTE_GAP', enforcement_class='scope',
                subject=target, message='Action target lacks current target-specific pre-route coverage; '
                + 'capabilities=' + ','.join(missing_caps or caps) + '; sources=' + ','.join(missing_sources),
                repairability='repairable', evidence=[{'target':target, 'missing_capabilities':missing_caps,
                    'missing_sources':missing_sources}],
                repair=_repair('route-action-target', target, turn_dir,
                    'Pre-route this actual target with scope and its applicable capabilities before executing the managed action.',
                    'Run the same explicit action once after its current target-specific Receipt is valid.', [target])))
    return findings


def evaluate_route_gate(
    *,
    turn_dir_raw: str,
    gate_id: str,
    phases: list[str],
    capabilities: list[str],
    semantic_reviewed: bool,
    unresolved: list[str],
    profile: str = "full",
    action_targets: list[str] | None = None,
    require_workflow: bool = False,
    require_target_routes: bool = False,
    require_acceptance: bool = False,
    require_content: bool | None = None,
    acceptance_stage: str = 'final',
) -> tuple[int, dict]:
    turn_dir = validate_turn_dir(turn_dir_raw)
    findings: list[dict]
    report: dict | None = None
    audit_code: int | None = None

    try:
        audit_code, report = route_audit(
            turn_dir_raw,
            phases,
            capabilities,
            semantic_reviewed,
            unresolved,
            True,
            explicit_targets=action_targets,
        )
        findings = _route_findings(report, turn_dir)
        if require_target_routes:
            findings.extend(_action_route_findings(turn_dir, list(action_targets or []), report))
    except (ActivityError, ReceiptError, Exception) as exc:
        # RouteError subclasses RuntimeError and is intentionally captured here too.
        # The Gate must fail closed if its upstream evidence cannot be evaluated.
        findings = [_finding(
            code="ROUTE_AUDIT_INVALID",
            enforcement_class="integrity",
            subject=exc.__class__.__name__,
            message=f"Post-route audit could not produce a trustworthy result: {exc}",
            repairability="blocked",
            evidence=[{"kind": "exception", "type": exc.__class__.__name__, "message": str(exc)}],
        )]

    if require_workflow:
        findings.extend(_obligation_findings(turn_dir, workflow_errors(turn_dir, action_targets),
            'INVESTIGATION_PLAN_REQUIRED',
            'Inspect the actual failure/call path, save the evidence and update the existing workflow evidence for all current requirements, targets and planned regression checks.'))
    if require_acceptance:
        findings.extend(_obligation_findings(turn_dir, acceptance_errors(turn_dir, acceptance_stage),
            'ACTUAL_TEST_EVIDENCE_REQUIRED',
            'Run the actual current checks through routing_activity check, retain their output and bind each applicable TEST to current candidate evidence.'))
    if require_content if require_content is not None else profile == 'full':
        targets = list(action_targets or [])
        if report is not None:
            targets += [f['subject'] for f in report.get('facts', [])
                        if f.get('kind') == 'path-change' and f.get('disposition') == 'mapped']
        if require_acceptance:
            targets += [posix_rel(turn_dir / name) for name in ('CHECKLIST.md', 'TEST.md', 'TURN.md')]
        findings.extend(_content_findings(turn_dir, targets))

    try:
        snapshot = _candidate_snapshot(turn_dir)
    except Exception as exc:
        snapshot = {
            "turn": posix_rel(turn_dir),
            "candidate_snapshot_error": exc.__class__.__name__,
            "candidate_snapshot_message": str(exc),
        }
        findings.append(_finding(
            code="CANDIDATE_SNAPSHOT_INVALID",
            enforcement_class="integrity",
            subject=exc.__class__.__name__,
            message=f"Gate could not build a trustworthy candidate fingerprint: {exc}",
            repairability="blocked",
            evidence=[{"kind": "exception", "type": exc.__class__.__name__, "message": str(exc)}],
        ))

    enforced_findings, deferred_findings = _profile_findings(findings, profile)

    adapter_evidence: list[dict] = [{
        "kind": "gate-profile",
        "profile": profile,
        "enforced_classes": sorted(_load_profile(profile)),
        "enforced_finding_ids": [
            __import__("gate_kernel").finding_id(f) for f in enforced_findings
        ],
        "deferred_finding_ids": [
            __import__("gate_kernel").finding_id(f) for f in deferred_findings
        ],
        "deferred_findings": [
            {
                "code": f.get("code"),
                "subject": f.get("subject"),
                "enforcement_class": f.get("enforcement_class"),
                "repairability": f.get("repairability"),
            }
            for f in deferred_findings
        ],
    }]
    if require_acceptance and acceptance_stage == 'publish':
        try:
            plan = json.loads((turn_dir / 'evidence/workflow.json').read_text(encoding='utf-8'))
            adapter_evidence.append({'kind': 'operation-preflight', 'stage': 'publish',
                'pending_post_delivery_tests': plan.get('post_delivery_tests', []),
                'boundary': 'Preflight proves local prerequisites; remote postconditions remain mandatory at finalization.'})
        except (OSError, ValueError):
            pass  # The enforced acceptance finding already reports this failure.
    if report is not None:
        _, _, report_path = audit_paths(turn_dir, load_audit_contract())
        if report_path.is_file():
            adapter_evidence.append({
                "path": posix_rel(report_path),
                "sha256": sha256_file(report_path),
                "audit_exit_code": audit_code,
                "audit_result": report.get("result"),
            })

    return evaluate_gate(
        turn_dir_raw=turn_dir,
        gate_id=gate_id,
        candidate_snapshot=snapshot,
        findings=enforced_findings,
        adapter="post-route-audit-v1",
        adapter_evidence=adapter_evidence,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Evaluate APCF Gate Kernel against current post-route audit state")
    ap.add_argument("--turn-dir", required=True)
    ap.add_argument("--gate-id", default=DEFAULT_GATE)
    ap.add_argument("--profile", default="full")
    ap.add_argument("--phase", action="append", default=[])
    ap.add_argument("--capability", action="append", default=[])
    ap.add_argument("--semantic-reviewed", action="store_true")
    ap.add_argument("--unresolved", action="append", default=[])
    args = ap.parse_args()

    try:
        code, record = evaluate_route_gate(
            turn_dir_raw=args.turn_dir,
            gate_id=args.gate_id,
            phases=list(args.phase),
            capabilities=list(args.capability),
            semantic_reviewed=bool(args.semantic_reviewed),
            unresolved=list(args.unresolved),
            profile=args.profile,
        )
        print(json.dumps(record, ensure_ascii=False, indent=2, sort_keys=True))
        print(f"{record['result']}: gate_id={record['gate_id']}; attempt_id={record['attempt_id']}; repairs={len(record['repair_set'])}")
        return code
    except GateError as exc:
        print(f"FAIL: {exc}")
        return exc.code
    except Exception as exc:
        print(f"FAIL: gate check internal error: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
