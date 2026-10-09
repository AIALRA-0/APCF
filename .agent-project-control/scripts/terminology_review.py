# APCF-META {"schema":1,"visibility":"public"}
#!/usr/bin/env python3
"""Create and validate reviewer-owned terminology evidence for final USER REPORTs.

The scanner is only a candidate finder. It never decides that a term is explained,
known to the reader, or exempt, and it does not judge whether a cited expansion is true.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

SCHEMA = 1
USER_REPORT_RE = re.compile(r"^## 1\.1\. USER REPORT\s*$", re.M)
TOP_RE = re.compile(r"^#{1,4}\s+([0-9])\.(?![0-9])\s+(.+?)\s*$", re.M)
TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Z]{2,}(?:-[A-Z0-9]{2,})*|"
    r"[A-Za-z]{1,12}[0-9]{1,4}(?:/[A-Za-z]{1,12}[0-9]{1,4})?)(?![A-Za-z0-9_])"
)
GLOSSARY_HEADER_RE = re.compile(r"(?m)^#{1,4}\s+2\.\s*术语表\s*$")
FENCE_RE = re.compile(r"(?ms)^\s*(`{3,}|~{3,}).*?^\s*\1\s*$")
INLINE_RE = re.compile(r"`[^`]*`")
LINK_TARGET_RE = re.compile(r"\]\([^)]+\)")
URL_RE = re.compile(r"https?://\S+")
URL_LOCATOR_RE = re.compile(r"https?://[^\s)>,]+", re.I)
DECISIONS = {"EXPLAINED", "KNOWN_TO_AUDIENCE", "LITERAL_FORMAT", "OUT_OF_SCOPE", "UNRESOLVED"}
NAME_STATUSES = {"VERIFIED", "UNVERIFIED", "NOT_APPLICABLE", "UNRESOLVED"}
ATTESTATIONS = {
    "complete_report_and_audience_checked",
    "official_names_verified_or_limits_explained",
    "terms_explain_their_role_in_this_task",
    "same_token_different_meanings_disambiguated",
}
PLACEHOLDERS = {
    "", "unknown", "n/a", "na", "tbd", "todo", "misc", "miscellaneous",
    "something", "some term", "a thing", "a vague term", "generic name",
    "generic description", "placeholder",
}


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_report_text(path: Path) -> str:
    """Read UTF-8 text with BOM handling and universal newline normalization."""
    with Path(path).open("r", encoding="utf-8-sig", newline=None) as stream:
        return stream.read()


def report_sections(report: str) -> tuple[list[int], dict[int, tuple[str, str, int, int]]]:
    matches = list(TOP_RE.finditer(report))
    sections: dict[int, tuple[str, str, int, int]] = {}
    order: list[int] = []
    for index, match in enumerate(matches):
        number = int(match.group(1))
        end = matches[index + 1].start() if index + 1 < len(matches) else len(report)
        sections[number] = (match.group(2).strip(), report[match.end():end].strip(), match.start(), end)
        order.append(number)
    return order, sections


def extract_user_report(text: str) -> str:
    """Return the exact trimmed 0–9 report body from TURN.md or a report-only file."""
    markers = list(USER_REPORT_RE.finditer(text))
    if markers:
        if len(markers) != 1:
            raise ValueError("TURN must contain exactly one '## 1.1. USER REPORT' marker")
        report = text[markers[0].end():].strip()
    else:
        report = text.strip()
    order, _ = report_sections(report)
    if order != list(range(10)):
        raise ValueError(f"final USER REPORT must contain top-level sections 0–9 in order; found {order}")
    return report


def has_final_user_report(path: Path) -> bool:
    """Recognize only a complete 0–9 USER REPORT embedded in a TURN file."""
    try:
        text = read_report_text(path)
        markers = list(USER_REPORT_RE.finditer(text))
        if len(markers) != 1:
            return False
        extract_user_report(text)
        return True
    except (OSError, UnicodeError, ValueError):
        return False


def has_user_report_candidate(path: Path) -> bool:
    """Select a report candidate for Gate, including malformed non-placeholder reports.

    The single template placeholder emitted by new_turn.py is ordinary in-progress
    content. Any other USER REPORT marker is in scope so a damaged final report
    cannot evade Gate merely because its 0–9 structure is malformed.
    """
    try:
        text = read_report_text(path)
    except (OSError, UnicodeError):
        return False
    markers = list(USER_REPORT_RE.finditer(text))
    if not markers:
        return False
    if len(markers) != 1:
        return True
    return text[markers[0].end():].strip() != "尚未收口"


def _blank(text: str) -> str:
    return "".join("\n" if char == "\n" else " " for char in text)


def _report_without_glossary(report: str) -> tuple[str, list[str]]:
    order, sections = report_sections(report)
    if 2 not in sections:
        return report, []
    _, body, start, end = sections[2]
    glossary_lines = [line.strip() for line in body.splitlines() if line.startswith("- ")]
    return report[:start] + _blank(report[start:end]) + report[end:], glossary_lines


def candidates(report_text: str) -> list[dict]:
    report = extract_user_report(report_text)
    text, _ = _report_without_glossary(report)
    text = FENCE_RE.sub(lambda match: _blank(match.group()), text)
    text = URL_RE.sub(" ", LINK_TARGET_RE.sub(" ", text))
    text = INLINE_RE.sub(" ", text)
    found: dict[str, dict[int, int]] = {}
    for number, source_line in enumerate(text.splitlines(), start=1):
        line = re.sub(
            r"【(?:PASS|FAIL|BLOCKED|未执行|进行中|不适用|TEST-[A-Za-z0-9_-]+|"
            r"CL-[A-Za-z0-9_-]+|对应 CL-[^】]+)】",
            " ",
            source_line,
        )
        line = re.sub(r"(?<![A-Za-z0-9_])(?:IT|TR|PA|CL|TEST|REG|MAT|ADR|RB|FT)-[0-9A-Za-z_-]+", " ", line)
        line = re.sub(r"(?<![A-Za-z0-9_])R\d{2}(?![A-Za-z0-9_])", " ", line)
        line = re.sub(r"(?i)(?<![A-Za-z0-9_])v\d+(?:\.\d+)*(?![A-Za-z0-9_])", " ", line)
        for match in TOKEN_RE.finditer(line):
            token = match.group()
            if token.isdecimal() or len(token) > 48:
                continue
            for term in token.split("/"):
                counts = found.setdefault(term, {})
                counts[number] = counts.get(number, 0) + 1
    return [
        {"term": term, "line_numbers": sorted(lines), "observed_uses": sum(lines.values())}
        for term, lines in sorted(found.items())
    ]


def glossary_lines(report_text: str) -> list[str]:
    report = extract_user_report(report_text)
    _, sections = report_sections(report)
    if 2 not in sections:
        return []
    body = sections[2][1]
    return [line.strip() for line in body.splitlines() if line.startswith("- ")]


def initial_review(report_text: str) -> dict:
    report = extract_user_report(report_text)
    rows = []
    for candidate in candidates(report):
        rows.append({
            "term": candidate["term"],
            "line_numbers": candidate["line_numbers"],
            "observed_uses": candidate["observed_uses"],
            "meanings": [{
                "meaning_id": "meaning-1",
                "line_numbers": candidate["line_numbers"],
                "decision": "UNRESOLVED",
                "reason": "",
                "audience_context": "",
                "domain_context": "",
                "current_use": "",
                "context_relevance": "",
                "name_status": "UNRESOLVED",
                "verified_full_name": "",
                "name_limit": "",
                "definition": "",
                "source_or_basis": "",
                "reviewer": "",
                "reviewed_at": "",
            }],
        })
    return {
        "schema": SCHEMA,
        "report_sha256": sha256_text(report),
        "reviewer": "",
        "reviewed_at": "",
        "audience_context": "",
        "semantic_review_completed": False,
        "coverage_scope": "Review the complete final USER REPORT and shared reader/domain context; add relevant Chinese terms the scanner cannot find.",
        "no_glossary_reason": "",
        "items": rows,
        "manual_terms": [],
        "attestations": {name: False for name in sorted(ATTESTATIONS)},
    }


def _is_placeholder(value: object) -> bool:
    return not isinstance(value, str) or value.strip().lower() in PLACEHOLDERS


def _has_credible_source_locator(value: object) -> bool:
    """Require a concrete source locator and reject reserved example URLs."""
    if not isinstance(value, str):
        return False
    urls = URL_LOCATOR_RE.findall(value)
    for raw_url in urls:
        host = (urlparse(raw_url).hostname or "").lower().rstrip(".")
        if (not host or host.startswith("example.")
                or host in {"example.com", "example.org", "example.net", "localhost"}
                or host.endswith((".invalid", ".example", ".test", ".localhost"))):
            continue
        return True
    return bool(re.search(r"(?:^|\s)(?:evidence|\.agent-project-control)/\S+", value, re.I))


def _valid_review_time(value: object) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _term_matches_line(term: str, line: str) -> bool:
    if re.search(r"[\u3400-\u9fff]", term):
        return term in line
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(term) + r"(?![A-Za-z0-9_])", line, re.I) is not None


def _glossary_matches(term: str, rows: list[str]) -> int:
    return sum(_term_matches_line(term, row) for row in rows)


def _validate_meaning(report: str, term: str, meaning: object, label: str) -> list[str]:
    issues: list[str] = []
    if not isinstance(meaning, dict):
        return [label + ": invalid meaning group"]
    for field in ("meaning_id", "reason", "audience_context", "domain_context", "current_use",
                  "context_relevance", "source_or_basis", "reviewer"):
        if not isinstance(meaning.get(field), str) or not meaning[field].strip():
            issues.append(label + ": missing " + field)
    if not _valid_review_time(meaning.get("reviewed_at")):
        issues.append(label + ": reviewed_at must be an ISO timestamp with timezone")
    decision = meaning.get("decision")
    if decision not in DECISIONS or decision == "UNRESOLVED":
        issues.append(label + ": unresolved or invalid decision")
    if not _is_placeholder(meaning.get("source_or_basis")) and len(str(meaning.get("source_or_basis", "")).strip()) < 12:
        issues.append(label + ": source_or_basis is too vague to identify a basis")
    if not _has_credible_source_locator(meaning.get("source_or_basis")):
        issues.append(label + ": missing a credible source locator or reviewer evidence path")
    name_status = meaning.get("name_status")
    full_name = meaning.get("verified_full_name", "")
    if name_status not in NAME_STATUSES or name_status == "UNRESOLVED":
        issues.append(label + ": official-name status is unresolved")
    if decision == "EXPLAINED":
        if not isinstance(meaning.get("definition"), str) or not meaning["definition"].strip():
            issues.append(label + ": explanation is missing")
        if not isinstance(meaning.get("context_relevance"), str) or not meaning["context_relevance"].strip():
            issues.append(label + ": current relevance is missing")
        if name_status == "VERIFIED":
            normalized = str(full_name).strip()
            if _is_placeholder(normalized) or len(normalized.split()) < 2:
                issues.append(label + ": verified full name is a placeholder or incomplete phrase")
        elif name_status == "UNVERIFIED":
            if str(full_name).strip():
                issues.append(label + ": unverified name must not include a guessed full name")
            if not isinstance(meaning.get("name_limit"), str) or not meaning["name_limit"].strip():
                issues.append(label + ": unverified name needs an explicit limit statement")
        elif name_status == "NOT_APPLICABLE":
            if str(full_name).strip():
                issues.append(label + ": not-applicable name status must not include a full name")
        if name_status not in {"VERIFIED", "UNVERIFIED", "NOT_APPLICABLE"}:
            issues.append(label + ": explanation needs a verified name, an explicit unknown limit, or a justified non-applicable name")
    elif decision in {"KNOWN_TO_AUDIENCE", "LITERAL_FORMAT", "OUT_OF_SCOPE"}:
        if not meaning.get("reason") or not str(meaning.get("reason")).strip():
            issues.append(label + ": exemption reason is missing")
        if not meaning.get("context_relevance") or not str(meaning.get("context_relevance")).strip():
            issues.append(label + ": exemption context is missing")
    return issues


def validate(report_text: str, review: dict) -> list[str]:
    try:
        report = extract_user_report(report_text)
    except ValueError as exc:
        return [str(exc)]
    issues: list[str] = []
    if not isinstance(review, dict) or review.get("schema") != SCHEMA:
        return ["invalid terminology review schema"]
    if review.get("report_sha256") != sha256_text(report):
        issues.append("review was prepared for a different final USER REPORT SHA")
    if review.get("semantic_review_completed") is not True:
        issues.append("terminology/content review is not completed by a human reviewer")
    for field in ("reviewer", "audience_context"):
        if not isinstance(review.get(field), str) or not review[field].strip():
            issues.append("missing review provenance: " + field)
    if not _valid_review_time(review.get("reviewed_at")):
        issues.append("reviewed_at must be an ISO timestamp with timezone")
    attestations = review.get("attestations")
    if (not isinstance(attestations, dict) or set(attestations) != ATTESTATIONS
            or any(attestations.get(name) is not True for name in ATTESTATIONS)):
        issues.append("whole-report, reader-context, source-limit, role and ambiguity attestations are incomplete")

    candidates_by_term = {row["term"]: row for row in candidates(report)}
    glossary = glossary_lines(report)
    if not glossary and (not isinstance(review.get("no_glossary_reason"), str)
                         or not review["no_glossary_reason"].strip()):
        issues.append("empty glossary needs a reviewer explanation")
    for field in ("items", "manual_terms"):
        if not isinstance(review.get(field), list):
            return issues + [field + " must be an array"]
    item_rows = review["items"]
    manual_rows = review["manual_terms"]
    observed_terms: set[str] = set()
    all_lines = report.splitlines()
    _, sections = report_sections(report)
    glossary_line_numbers = set()
    if 2 in sections:
        _, _, start, end = sections[2]
        glossary_line_numbers = set(range(report[:start].count("\n") + 1, report[:end].count("\n") + 2))

    required_items = set(candidates_by_term)
    seen_items: set[str] = set()
    for index, row in enumerate(item_rows):
        label = f"candidate item {index}"
        if not isinstance(row, dict) or not isinstance(row.get("term"), str) or not row["term"].strip():
            issues.append(label + ": invalid term")
            continue
        term = row["term"].strip()
        if term in observed_terms:
            issues.append(label + ": duplicate term " + term)
        observed_terms.add(term)
        seen_items.add(term)
        candidate = candidates_by_term.get(term)
        if candidate is None:
            issues.append(label + ": candidate is absent from the current report: " + term)
            expected_lines: set[int] = set()
        else:
            expected_lines = set(candidate["line_numbers"])
            listed = row.get("line_numbers")
            if not isinstance(listed, list) or set(listed) != expected_lines:
                issues.append(label + ": occurrence lines differ from the current scan: " + term)
        issues.extend(_validate_term_uses(report, term, row, expected_lines, label))
    for missing in sorted(required_items - seen_items):
        issues.append("unreviewed abbreviation candidate: " + missing)

    for index, row in enumerate(manual_rows):
        label = f"manual term {index}"
        if not isinstance(row, dict) or not isinstance(row.get("term"), str) or not row["term"].strip():
            issues.append(label + ": invalid term")
            continue
        term = row["term"].strip()
        if term in observed_terms:
            issues.append(label + ": duplicate term " + term)
        observed_terms.add(term)
        if term in candidates_by_term:
            issues.append(label + ": scanner candidate must be reviewed under items: " + term)
        listed = row.get("line_numbers")
        if not isinstance(listed, list) or not listed or any(
                not isinstance(number, int) or number < 1 or number > len(all_lines)
                or number in glossary_line_numbers or not _term_matches_line(term, all_lines[number - 1])
                for number in listed):
            issues.append(label + ": report occurrence lines are missing or invalid")
            expected_lines = set()
        else:
            expected_lines = set(listed)
            actual_lines = {n for n, line in enumerate(all_lines, 1)
                            if n not in glossary_line_numbers and _term_matches_line(term, line)}
            if expected_lines != actual_lines:
                issues.append(label + ": manual term occurrence coverage is incomplete: " + term)
        issues.extend(_validate_term_uses(report, term, row, expected_lines, label))
    if item_rows and seen_items != required_items:
        # Missing rows are also reported individually above; this makes extra stale rows explicit.
        for extra in sorted(seen_items - required_items):
            issues.append("review contains a stale or manual term under items: " + extra)
    return issues


def _validate_term_uses(report: str, term: str, row: dict, expected_lines: set[int], label: str) -> list[str]:
    issues: list[str] = []
    meanings = row.get("meanings")
    if not isinstance(meanings, list) or not meanings:
        return [label + ": meanings must contain reviewer-checked usage groups"]
    assigned: set[int] = set()
    meaning_ids: set[str] = set()
    explained = 0
    for index, meaning in enumerate(meanings):
        meaning_label = f"{label} {term} meaning {index}"
        if not isinstance(meaning, dict):
            issues.append(meaning_label + ": invalid meaning group")
            continue
        meaning_lines = meaning.get("line_numbers")
        if (not isinstance(meaning_lines, list) or not meaning_lines
                or any(not isinstance(number, int) or number < 1 or number > len(report.splitlines()) for number in meaning_lines)):
            issues.append(meaning_label + ": usage lines are missing or invalid")
        else:
            line_set = set(meaning_lines)
            if len(line_set) != len(meaning_lines):
                issues.append(meaning_label + ": duplicate usage line")
            if assigned & line_set:
                issues.append(meaning_label + ": usage line assigned to multiple meanings")
            assigned.update(line_set)
            if not line_set <= expected_lines:
                issues.append(meaning_label + ": usage line is outside this term's current occurrences")
        meaning_id = meaning.get("meaning_id")
        if isinstance(meaning_id, str) and meaning_id.strip():
            if meaning_id in meaning_ids:
                issues.append(meaning_label + ": duplicate meaning_id")
            meaning_ids.add(meaning_id)
        issues.extend(_validate_meaning(report, term, meaning, meaning_label))
        if meaning.get("decision") == "EXPLAINED":
            explained += 1
    if assigned != expected_lines:
        issues.append(label + ": reviewer meaning groups do not cover every current occurrence of " + term)
    if _glossary_matches(term, glossary_lines(report)) < explained:
        issues.append(label + ": explained usage group is missing a matching glossary bullet: " + term)
    return issues


def _private_sidecar_payload(path: Path) -> bytes:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return (f'# APCF-META {{"schema":1,"visibility":"private"}}\n'
            f"schema: 1\nvisibility: private\nsha256: {digest}\n").encode("utf-8")


def write_private_sidecar(path: Path) -> None:
    """Refresh only the metadata sidecar after an authorized review edit."""
    sidecar = path.with_name(path.name + ".apcf-meta.yaml")
    if sidecar.is_file():
        previous = sidecar.read_text(encoding="utf-8")
        if re.search(r"(?m)^visibility:\s*public\s*$", previous):
            raise ValueError(f"refusing to reclassify public review evidence as private: {sidecar}")
    sidecar.write_bytes(_private_sidecar_payload(path))


def private_sidecar_errors(path: Path) -> list[str]:
    sidecar = path.with_name(path.name + ".apcf-meta.yaml")
    try:
        text = sidecar.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ["private terminology evidence sidecar is missing or unreadable"]
    if not re.search(r"(?m)^visibility:\s*private\s*$", text):
        return ["terminology evidence sidecar must declare visibility: private"]
    schema = re.search(r"(?m)^schema:\s*(\d+)\s*$", text)
    digest = re.search(r"(?m)^sha256:\s*([0-9a-f]{64})\s*$", text)
    if not schema or schema.group(1) != "1" or not digest:
        return ["terminology evidence sidecar has an invalid schema or digest"]
    if digest.group(1) != hashlib.sha256(path.read_bytes()).hexdigest():
        return ["terminology evidence sidecar digest is stale"]
    return []


def _write_review(path: Path, review: dict, overwrite: bool = False) -> None:
    if path.exists() and not overwrite:
        raise ValueError("refusing to overwrite an existing terminology review")
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(review, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    path.write_bytes(payload)
    write_private_sidecar(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("scan", "init", "verify"))
    parser.add_argument("--report", required=True, help="TURN.md containing USER REPORT, or the report 0–9 itself")
    parser.add_argument("--review")
    parser.add_argument("--output")
    args = parser.parse_args()
    try:
        report = extract_user_report(read_report_text(Path(args.report)))
        if args.command == "scan":
            result = {"report_sha256": sha256_text(report), "candidates": candidates(report),
                      "glossary_entries": len(glossary_lines(report))}
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0
        if args.command == "init":
            if not args.output:
                raise ValueError("--output is required for init")
            _write_review(Path(args.output), initial_review(report))
            print("DRAFT: candidate groups are UNRESOLVED; no semantic review or PASS was claimed")
            return 0
        if not args.review:
            raise ValueError("--review is required for verify")
        review_path = Path(args.review)
        review = json.loads(review_path.read_text(encoding="utf-8"))
        issues = validate(report, review)
        if review_path.exists():
            issues.extend(private_sidecar_errors(review_path))
        for issue in issues:
            print("FAIL:", issue)
        if issues:
            print("BLOCKED: terminology review evidence is incomplete or stale")
            return 2
        print("PASS_STRUCTURE_ONLY: report binding and reviewer-evidence structure are current; semantic truth remains the named reviewer's responsibility")
        return 0
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        print(f"BLOCKED: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
