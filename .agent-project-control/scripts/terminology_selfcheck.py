# APCF-META {"schema":1,"visibility":"public"}
#!/usr/bin/env python3
"""Focused positive and negative checks for final-report terminology review."""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import gate_check
import routing_activity
import terminology_review as terms


def _report(*, glossary: bool = True, known_reader: bool = False) -> str:
    if known_reader:
        term_lines = ""
        body = "The API is the established interface already used by maintainers."
    elif glossary:
        term_lines = "\n".join([
            "- ACL (software): Access Control List, a rule list that limits access to a resource.",
            "- ACL (medicine): Anterior Cruciate Ligament, a ligament that stabilizes the knee.",
            "- API: Application Programming Interface, the callable surface used by this tool.",
            "- IPv4: Internet Protocol version 4, one network addressing version.",
            "- IPv6: Internet Protocol version 6, a separate network addressing version.",
            "- ZXQ: A local label; no official expansion was verified, so this report does not invent one.",
            "- 零拷贝：本报告中指复用缓冲区以避免一次额外复制",
        ])
        body = "\n".join([
            "Software security uses an ACL to restrict access to the internal service.",
            "Sports medicine may report an ACL tear that affects knee stability.",
            "The local tool exposes an API for scripts and records separate domain API calls.",
            "The protocol accepts IPv4 and IPv6 addresses as distinct formats.",
            "The internal label ZXQ has no public product reference in the available source.",
            "The report uses 零拷贝 to describe shared buffer reuse.",
        ])
    else:
        term_lines = ""
        body = "普通读者可以直接理解这份报告中的结果和边界"
    sections = [
        ("精确状态头", "- 当前状态：合成语义审查夹具"),
        ("承上启下", "This fixture provides a complete report shape for deterministic checks."),
        ("术语表", term_lines),
        ("执行清单", "- Synthetic review scope"),
        ("验收记录", "- Synthetic evidence scope"),
        ("完整讲解", body),
        ("关键要点", "- **候选仅供人工判断**：The scanner reports occurrences and never assigns an accepted decision."),
        ("用户需要执行", "- **无需额外操作**：This fixture has no user action."),
        ("需要继续讨论、搜索或决策", "- **没有额外决策**：This fixture has no open decision."),
        ("下一步推荐", "- **保持人工判断**：Reviewers must verify the actual source and audience context."),
    ]
    return "\n\n".join(f"## {index}. {title}\n\n{content}" for index, (title, content) in enumerate(sections))


def _meaning(term: str, line_numbers: list[int], *, decision="EXPLAINED", domain="software",
             full_name="", name_status="VERIFIED", definition="The meaning used in this report.",
             source="Verified source: https://developer.mozilla.org/en-US/docs/Glossary/API") -> dict:
    now = datetime.now().astimezone().isoformat()
    return {
        "meaning_id": f"{term.lower()}-{domain.replace(' ', '-')}",
        "line_numbers": line_numbers,
        "decision": decision,
        "reason": "This judgment matches the use and the current report context.",
        "audience_context": "Technical readers using this synthetic cross-domain report.",
        "domain_context": domain,
        "current_use": "Identifies the concept used in this report section.",
        "context_relevance": "The meaning changes how the reader interprets the reported result.",
        "name_status": name_status,
        "verified_full_name": full_name,
        "name_limit": "No official expansion was verified in the cited source." if name_status == "UNVERIFIED" else "",
        "definition": definition,
        "source_or_basis": source,
        "reviewer": "Synthetic human reviewer",
        "reviewed_at": now,
    }


def _complete_review(report: str, *, known_reader: bool = False) -> dict:
    review = terms.initial_review(report)
    now = datetime.now().astimezone().isoformat()
    review.update({
        "reviewer": "Synthetic human reviewer",
        "reviewed_at": now,
        "audience_context": "Technical readers; the report states any domain-specific use at the point of use.",
        "semantic_review_completed": True,
        "no_glossary_reason": "The only candidate is already shared reader context; no unfamiliar term needs expansion." if known_reader else "",
        "attestations": {name: True for name in sorted(terms.ATTESTATIONS)},
    })
    if known_reader:
        row = review["items"][0]
        row["meanings"] = [_meaning(row["term"], row["line_numbers"], decision="KNOWN_TO_AUDIENCE",
                                    domain="software", name_status="NOT_APPLICABLE", full_name="",
                                    definition="", source="Shared API context grounded in the current project architecture: .agent-project-control/ARCHITECTURE.md")]
        return review
    by_term = {row["term"]: row for row in review["items"]}
    for term, row in by_term.items():
        line_numbers = row["line_numbers"]
        if term == "ACL":
            row["meanings"] = [
                _meaning(term, [line_numbers[0]], domain="software security", full_name="Access Control List",
                         definition="A set of rules that limits access to a resource.",
                         source="Microsoft Learn: https://learn.microsoft.com/en-us/windows/win32/secauthz/access-control-lists"),
                _meaning(term, [line_numbers[1]], domain="sports medicine", full_name="Anterior Cruciate Ligament",
                         definition="A ligament that helps stabilize the knee.",
                         source="MedlinePlus: https://medlineplus.gov/ency/article/001074.htm"),
            ]
        elif term == "API":
            row["meanings"] = [_meaning(term, line_numbers, full_name="Application Programming Interface",
                                        definition="The callable surface through which this tool exposes operations.")]
        elif term == "IPv4":
            row["meanings"] = [_meaning(term, line_numbers, domain="networking", full_name="Internet Protocol version 4",
                                        definition="One version of the Internet Protocol used for network addressing.",
                                        source="RFC Editor: https://www.rfc-editor.org/info/rfc791/")]
        elif term == "IPv6":
            row["meanings"] = [_meaning(term, line_numbers, domain="networking", full_name="Internet Protocol version 6",
                                        definition="A separate version of the Internet Protocol with a different address format.",
                                        source="RFC Editor: https://www.rfc-editor.org/info/rfc8200/")]
        elif term == "ZXQ":
            row["meanings"] = [_meaning(term, line_numbers, domain="project-local label", name_status="UNVERIFIED",
                                        full_name="", definition="A local label for the component in this report.",
                                        source="No official expansion was found in this bounded source review; the label appears only in this report context: evidence/human-review-note.md")]
        else:
            row["meanings"] = [_meaning(term, line_numbers, full_name=term + " term",
                                        definition="The term's role in this synthetic report.")]
    # A manually supplied Chinese term is checked in report prose; glossary
    # bullets are evidence of explanation, not occurrences to review again.
    manual_line_numbers = [number for number, line in enumerate(report.splitlines(), 1)
                           if "零拷贝" in line and not line.startswith("- 零拷贝：")]
    if manual_line_numbers:
        review["manual_terms"] = [{
            "term": "零拷贝",
            "line_numbers": manual_line_numbers,
            "meanings": [_meaning("零拷贝", manual_line_numbers, domain="software memory behavior",
                                  name_status="NOT_APPLICABLE", full_name="",
                                  definition="Reuse of an existing buffer to avoid an additional copy.",
                                  source="Report context and reviewer evidence path: evidence/human-review-note.md")],
        }]
    return review


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


def _write_text(path: Path, value: str, visibility="private") -> None:
    payload = value.encode("utf-8")
    _write_private(path, payload)
    if visibility == "private":
        sidecar = path.with_name(path.name + ".apcf-meta.yaml")
        digest = hashlib.sha256(payload).hexdigest()
        sidecar.write_text(
            '# APCF-META {"schema":1,"visibility":"private"}\n'
            f"schema: 1\nvisibility: private\nsha256: {digest}\n",
            encoding="utf-8",
        )


def _write_dir_marker(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    marker = path / ".apcf-dir.yaml"
    if not marker.exists():
        marker.write_text('# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n', encoding="utf-8")


def _case_result(results: list[dict], name: str, passed: bool, detail: str) -> None:
    results.append({"case": name, "result": "PASS" if passed else "FAIL", "detail": detail})
    if not passed:
        raise AssertionError(f"{name}: {detail}")


def run(evidence_dir: Path) -> dict:
    evidence_dir = evidence_dir.resolve()
    if not evidence_dir.is_dir():
        raise ValueError("--evidence-dir must be an existing PA evidence directory")
    results: list[dict] = []

    report = _report()
    scanned = terms.candidates(report)
    by_term = {row["term"]: row for row in scanned}
    _case_result(results, "cross-domain and multi-acronym scan", set(by_term) >= {"ACL", "API", "IPv4", "IPv6", "ZXQ"}
                 and len(by_term["IPv4"]["line_numbers"]) == 1 and len(by_term["IPv6"]["line_numbers"]) == 1,
                 f"separate candidates={sorted(by_term)}")

    draft = terms.initial_review(report)
    _case_result(results, "scan/init remains unresolved", draft["semantic_review_completed"] is False
                 and all(group["decision"] == "UNRESOLVED" for row in draft["items"] for group in row["meanings"])
                 and all(value is False for value in draft["attestations"].values()),
                 "init assigned no reviewer decision or PASS")

    review = _complete_review(report)
    errors = terms.validate(report, review)
    _case_result(results, "manual Chinese term and unknown name boundary", not errors
                 and any(row["term"] == "零拷贝" for row in review["manual_terms"])
                 and all(not group["verified_full_name"] for row in review["items"] if row["term"] == "ZXQ" for group in row["meanings"]),
                 "Chinese term was manually covered; ZXQ remains unexpanded with a source limit")
    acl = next(row for row in review["items"] if row["term"] == "ACL")
    _case_result(results, "same abbreviation disambiguated by domain", len(acl["meanings"]) == 2
                 and {group["domain_context"] for group in acl["meanings"]} == {"software security", "sports medicine"},
                 "ACL uses have separate software and medical meanings")

    known_report = _report(known_reader=True)
    known_review = _complete_review(known_report, known_reader=True)
    _case_result(results, "known-reader exemption", not terms.validate(known_report, known_review)
                 and known_review["items"][0]["meanings"][0]["decision"] == "KNOWN_TO_AUDIENCE",
                 "reader-context reason allows an empty glossary without a term-count threshold")

    empty_report = _report(glossary=False)
    empty_review = _complete_review(empty_report)
    empty_review["no_glossary_reason"] = "The report contains no unfamiliar technical terms for its stated audience."
    _case_result(results, "empty glossary needs and accepts an explanation", not terms.validate(empty_report, empty_review),
                 "an empty glossary passes only with a reviewer explanation")
    empty_review["no_glossary_reason"] = ""
    _case_result(results, "empty glossary without explanation blocks", any("empty glossary" in issue for issue in terms.validate(empty_report, empty_review)),
                 "missing empty-glossary reason was rejected")

    vague_review = json.loads(json.dumps(review, ensure_ascii=False))
    vague_acl = next(row for row in vague_review["items"] if row["term"] == "ACL")
    vague_acl["meanings"][0]["verified_full_name"] = "A vague term"
    _case_result(results, "vague full-name placeholder blocks", any("placeholder or incomplete phrase" in issue for issue in terms.validate(report, vague_review)),
                 "a vague placeholder cannot satisfy a verified expansion")

    unsupported_review = json.loads(json.dumps(review, ensure_ascii=False))
    unsupported_acl = next(row for row in unsupported_review["items"] if row["term"] == "ACL")
    unsupported_acl["meanings"][0]["verified_full_name"] = "Advanced Clinical Language"
    unsupported_acl["meanings"][0]["source_or_basis"] = "A plausible guess without a source"
    _case_result(results, "unsupported pseudo-expansion blocks", any("credible source locator" in issue for issue in terms.validate(report, unsupported_review)),
                 "a plausible-sounding full name without a source locator was rejected")

    fake_source_review = json.loads(json.dumps(review, ensure_ascii=False))
    fake_source_acl = next(row for row in fake_source_review["items"] if row["term"] == "ACL")
    fake_source_acl["meanings"][0]["verified_full_name"] = "Advanced Clinical Language"
    fake_source_acl["meanings"][0]["source_or_basis"] = "Fake lookup: https://example.invalid/acl"
    _case_result(results, "reserved fake source cannot support a pseudo-expansion",
                 any("credible source locator" in issue for issue in terms.validate(report, fake_source_review)),
                 "reserved example domains are rejected as source evidence")

    changed_report = report.replace("internal service", "replacement service", 1)
    _case_result(results, "stale report SHA blocks", any("different final USER REPORT SHA" in issue for issue in terms.validate(changed_report, review)),
                 "a report edit invalidates the bound review")

    gate_fixture = evidence_dir / "terminology-selfcheck-gate"
    _write_dir_marker(gate_fixture)
    gate_turn = gate_fixture / "TR-TERM-GATE-FOCUSED"
    _write_dir_marker(gate_turn)
    _write_dir_marker(gate_turn / "evidence")
    turn_report = report
    turn_payload = (
        '# APCF-META {"schema":1,"visibility":"private"}\n'
        "# Synthetic terminology Gate fixture\n\n"
        "- **Status**：IN_PROGRESS\n\n"
        "## 1.1. USER REPORT\n\n" + turn_report + "\n"
    )
    _write_text(gate_turn / "REQUEST.md", "Synthetic Gate fixture; private evidence only.\n")
    _write_text(gate_turn / "CHECKLIST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic checklist\n")
    _write_text(gate_turn / "TEST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic tests\n")
    _write_text(gate_turn / "TURN.md", turn_payload)
    _write_text(gate_turn / "evidence/human-review-note.md", "Synthetic human review evidence for isolated Gate checks.\n")
    _write_text(gate_turn / "evidence/terms-review.json", json.dumps(_complete_review(turn_report), ensure_ascii=False, indent=2) + "\n")
    target = (gate_turn / "TURN.md").resolve().relative_to(ROOT.resolve()).as_posix()
    observation_line = turn_payload.splitlines().index("## 1.1. USER REPORT") + 2
    routing_activity.record_content_review(
        str(gate_turn), target, ["writing", "style"], ["evidence/human-review-note.md"],
        [{"line": observation_line, "criterion": "whole-report terminology and reader-context review",
          "observed": "Each fixture use is assigned to a reviewed meaning group; unknown expansion remains unexpanded.",
          "result": "PASS"}], method="synthetic-focused-gate-test",
        terms_review_path="evidence/terms-review.json",
    )
    _case_result(results, "content review records the terms evidence", not routing_activity.content_review_errors(gate_turn, target, ["writing", "style"]),
                 "the existing content-review row binds the report and private terminology evidence")

    crlf_turn = gate_fixture / "TR-TERM-CRLF-REPORT"
    _write_dir_marker(crlf_turn)
    _write_dir_marker(crlf_turn / "evidence")
    _write_text(crlf_turn / "REQUEST.md", "Synthetic CRLF report regression fixture.\n")
    _write_text(crlf_turn / "CHECKLIST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic checklist\n")
    _write_text(crlf_turn / "TEST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic tests\n")
    crlf_turn_payload = turn_payload.replace("\n", "\r\n")
    _write_text(crlf_turn / "TURN.md", crlf_turn_payload)
    _write_text(crlf_turn / "evidence/human-review-note.md", "Synthetic human review evidence for CRLF report checks.\n")
    crlf_target = (crlf_turn / "TURN.md").resolve().relative_to(ROOT.resolve()).as_posix()
    init_path = crlf_turn / "evidence/terms-review-draft.json"
    init_run = subprocess.run(
        [sys.executable, "-B", str(SCRIPT_DIR / "terminology_review.py"), "init",
         "--report", str(crlf_turn / "TURN.md"), "--output", str(init_path)],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8",
    )
    draft = json.loads(init_path.read_text(encoding="utf-8")) if init_path.is_file() else {}
    normalized_report = terms.extract_user_report(terms.read_report_text(crlf_turn / "TURN.md"))
    crlf_review = _complete_review(normalized_report)
    init_aligned = (init_run.returncode == 0
                    and draft.get("report_sha256") == crlf_review.get("report_sha256")
                    and draft.get("semantic_review_completed") is False
                    and all(group["decision"] == "UNRESOLVED"
                            for row in draft.get("items", []) for group in row.get("meanings", [])))
    _case_result(results, "real CRLF report init uses universal newline SHA",
                 init_aligned and b"\r\n" in (crlf_turn / "TURN.md").read_bytes()
                 and b"\n" not in (crlf_turn / "TURN.md").read_bytes().replace(b"\r\n", b""),
                 "CLI init on a byte-level CRLF TURN produces the same reviewer SHA as normalized report text and remains unresolved")
    _write_text(crlf_turn / "evidence/terms-review.json", json.dumps(crlf_review, ensure_ascii=False, indent=2) + "\n")
    crlf_observation_line = crlf_turn_payload.splitlines().index("## 1.1. USER REPORT") + 2
    routing_activity.record_content_review(
        str(crlf_turn), crlf_target, ["writing", "style"], ["evidence/human-review-note.md"],
        [{"line": crlf_observation_line, "criterion": "current CRLF final report terminology review",
          "observed": "The review SHA agrees with the normalized report read by the content-review path.", "result": "PASS"}],
        method="synthetic-focused-crlf-gate-test",
    )
    _case_result(results, "CRLF record_content_review binds terms evidence",
                 not routing_activity.content_review_errors(crlf_turn, crlf_target, ["writing", "style"]),
                 "a review initialized from the CRLF file is accepted by the current content-review validator")

    with patch.object(gate_check, "route_audit", return_value=(0, {"result": "PASS", "facts": []})), \
            patch.object(gate_check, "_candidate_snapshot", return_value={"turn": crlf_target, "fixture": "crlf-focused"}):
        code, record = gate_check.evaluate_route_gate(
            turn_dir_raw=str(crlf_turn), gate_id="route-readiness", phases=[], capabilities=[],
            semantic_reviewed=False, unresolved=[], profile="full", action_targets=[crlf_target], require_content=True,
        )
        _case_result(results, "Full Gate accepts current CRLF terminology evidence",
                     code == 0 and record["result"] == "PASS",
                     f"result={record['result']} exit={code}")

        edited_text = terms.read_report_text(crlf_turn / "TURN.md").replace("internal service", "modified service", 1)
        _write_text(crlf_turn / "TURN.md", edited_text.replace("\n", "\r\n"))
        stale_errors = routing_activity.content_review_errors(crlf_turn, crlf_target, ["writing", "style"])
        code, record = gate_check.evaluate_route_gate(
            turn_dir_raw=str(crlf_turn), gate_id="route-readiness", phases=[], capabilities=[],
            semantic_reviewed=False, unresolved=[], profile="full", action_targets=[crlf_target], require_content=True,
        )
        stale_findings = [finding for finding in record["findings"]
                          if finding.get("code") == "CONTENT_ACCEPTANCE_REQUIRED"
                          and "different final USER REPORT SHA" in finding.get("message", "")]
        _case_result(results, "edited CRLF report makes terminology stale and blocks Gate",
                     any("different final USER REPORT SHA" in issue for issue in stale_errors)
                     and code != 0 and bool(stale_findings),
                     f"result={record['result']} exit={code}; stale-terminology findings={len(stale_findings)}")

    placeholder_turn = gate_fixture / "TR-TERM-INITIAL-PLACEHOLDER"
    _write_dir_marker(placeholder_turn)
    _write_dir_marker(placeholder_turn / "evidence")
    _write_text(placeholder_turn / "REQUEST.md", "Synthetic initial-placeholder review fixture.\n")
    _write_text(placeholder_turn / "CHECKLIST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic checklist\n")
    _write_text(placeholder_turn / "TEST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic tests\n")
    placeholder_payload = "# Synthetic in-progress Turn\n\n- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n尚未收口\n"
    _write_text(placeholder_turn / "TURN.md", placeholder_payload)
    _write_text(placeholder_turn / "evidence/review-note.md", "Synthetic review of the unchanged in-progress placeholder.\n")
    placeholder_target = (placeholder_turn / "TURN.md").resolve().relative_to(ROOT.resolve()).as_posix()
    routing_activity.record_content_review(
        str(placeholder_turn), placeholder_target, ["writing", "style"], ["evidence/review-note.md"],
        [{"line": placeholder_payload.splitlines().index("## 1.1. USER REPORT") + 1,
          "criterion": "initial Turn template content", "observed": "The exact unclosed-report placeholder remains unchanged.", "result": "PASS"}],
        method="synthetic-focused-placeholder-test",
    )
    _case_result(results, "initial placeholder keeps ordinary content-review semantics",
                 not routing_activity.content_review_errors(placeholder_turn, placeholder_target, ["writing", "style"])
                 and not terms.has_user_report_candidate(placeholder_turn / "TURN.md"),
                 "the exact new_turn.py placeholder does not require a glossary ledger")

    malformed_turn = gate_fixture / "TR-TERM-MALFORMED-REPORT"
    _write_dir_marker(malformed_turn)
    _write_dir_marker(malformed_turn / "evidence")
    _write_text(malformed_turn / "REQUEST.md", "Synthetic malformed-report review fixture.\n")
    _write_text(malformed_turn / "CHECKLIST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic checklist\n")
    _write_text(malformed_turn / "TEST.md", "<!-- APCF-META {\"schema\":1,\"visibility\":\"private\"} -->\n# Synthetic tests\n")
    malformed_payload = "# Synthetic damaged Turn\n\n- **Status**：IN_PROGRESS\n\n## 1.1. USER REPORT\n\n## 0. Status\n\nIncomplete final report\n"
    _write_text(malformed_turn / "TURN.md", malformed_payload)
    _write_text(malformed_turn / "evidence/review-note.md", "Synthetic review note for malformed report rejection.\n")
    malformed_target = (malformed_turn / "TURN.md").resolve().relative_to(ROOT.resolve()).as_posix()
    malformed_blocked = False
    try:
        routing_activity.record_content_review(
            str(malformed_turn), malformed_target, ["writing", "style"], ["evidence/review-note.md"],
            [{"line": 3, "criterion": "final report structure", "observed": "Malformed report was rejected.", "result": "PASS"}],
            method="synthetic-focused-malformed-report-test",
        )
    except routing_activity.ActivityError:
        malformed_blocked = True
    _case_result(results, "damaged USER REPORT cannot evade terminology scope",
                 malformed_blocked and terms.has_user_report_candidate(malformed_turn / "TURN.md"),
                 "a non-placeholder USER REPORT marker with incomplete 0-9 structure is a Gate candidate and content-review recording blocks")

    with patch.object(gate_check, "route_audit", return_value=(0, {"result": "PASS", "facts": []})), \
            patch.object(gate_check, "_candidate_snapshot", return_value={"turn": target, "fixture": "focused"}):
        code, record = gate_check.evaluate_route_gate(
            turn_dir_raw=str(gate_turn), gate_id="route-readiness", phases=[], capabilities=[],
            semantic_reviewed=False, unresolved=[], profile="full", action_targets=[target], require_content=True,
        )
        _case_result(results, "Full Gate accepts current terminology evidence", code == 0 and record["result"] == "PASS",
                     f"result={record['result']} exit={code}")

        stale = json.loads((gate_turn / "evidence/terms-review.json").read_text(encoding="utf-8"))
        stale["report_sha256"] = "0" * 64
        _write_text(gate_turn / "evidence/terms-review.json", json.dumps(stale, ensure_ascii=False, indent=2) + "\n")
        code, record = gate_check.evaluate_route_gate(
            turn_dir_raw=str(gate_turn), gate_id="route-readiness", phases=[], capabilities=[],
            semantic_reviewed=False, unresolved=[], profile="full", action_targets=[target], require_content=True,
        )
        terminology_findings = [finding for finding in record["findings"]
                                if finding.get("code") == "CONTENT_ACCEPTANCE_REQUIRED"
                                and "terminology review" in finding.get("message", "")]
        _case_result(results, "Full Gate blocks stale terminology SHA", code != 0 and bool(terminology_findings),
                     f"result={record['result']} exit={code}; findings={len(terminology_findings)}")

    result = {
        "schema": 1,
        "scope": "focused terminology review checks; route audit and candidate snapshot were isolated in the Full Gate adapter call",
        "cases": results,
        "gate_fixture": target,
        "positive_gate_result": "PASS",
        "negative_gate_result": "BLOCKED_OR_REPAIR_REQUIRED",
    }
    output = evidence_dir / "terminology-selfcheck.json"
    if output.exists():
        raise FileExistsError(f"refusing to overwrite focused evidence: {output}")
    payload = (json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    output.write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    output.with_name(output.name + ".apcf-meta.yaml").write_text(
        '# APCF-META {"schema":1,"visibility":"private"}\n'
        f"schema: 1\nvisibility: private\nsha256: {digest}\n",
        encoding="utf-8",
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-dir", required=True, help="current PA evidence/ directory")
    args = parser.parse_args()
    try:
        result = run(Path(args.evidence_dir))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"PASS: terminology focused cases={len(result['cases'])}")
        return 0
    except Exception as exc:
        print(f"FAIL: terminology focused selfcheck: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
