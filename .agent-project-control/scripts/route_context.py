# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from routing_receipt import (
    ReceiptError,
    authority_snapshot,
    record_route_receipt,
    source_snapshot,
    validate_turn_dir,
    verify_snapshot_rows,
)

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = ROOT / ".agent-project-control"
RULE_HEADING_RE = re.compile(r"^##\s+\d+\.\d+\.\s+(R\d{2})\b", re.MULTILINE)
INDEX_ROW_RE = re.compile(r"^\|\s*`(R\d{2})`\s*\|\s*`([^`]+)`\s*\|\s*$", re.MULTILINE)
SKILL_ID_RE = re.compile(r"^\s*-\s+id:\s*([^\s#]+)\s*$")
COMMIT_RE = re.compile(r"^\s+resolved_commit:\s*([^\s#]+)\s*$")
SKILL_SHA_RE = re.compile(r"^\s+skill_file_sha256:\s*([0-9a-fA-F]{64})\s*$")
SKILL_MODE_RE = re.compile(r"^\s+install_mode:\s*([^\s#]+)\s*$")

EXIT_INVALID = 2
EXIT_UNRESOLVED = 3


class RouteError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class Source:
    kind: str
    path: Path
    label: str


def load_contract() -> dict:
    framework = FRAMEWORK_ROOT / "framework.yaml"
    text = framework.read_text(encoding="utf-8")
    m = re.search(r'^routing_contract:\s*["\']([^"\']+)["\']\s*$', text, re.MULTILINE)
    if not m:
        raise RouteError("routing_contract is missing from framework.yaml")
    contract_path = ROOT / m.group(1)
    if not contract_path.is_file():
        raise RouteError(f"routing contract missing: {contract_path.relative_to(ROOT)}")
    with contract_path.open("rb") as fh:
        data = tomllib.load(fh)
    if data.get("schema") != 1:
        raise RouteError("unsupported routing contract schema")
    return data


def parse_rule_index(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    pairs = INDEX_ROW_RE.findall(text)
    mapping: dict[str, str] = {}
    for rid, module in pairs:
        if rid in mapping:
            raise RouteError(f"duplicate Rule ID in rules index: {rid}")
        mapping[rid] = module
    expected = {f"R{i:02d}" for i in range(1, 32)}
    actual = set(mapping)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        raise RouteError(f"rules index coverage mismatch; missing={missing}; unknown={unknown}")
    return mapping


def scan_canonical_rules(rules_root: Path) -> dict[str, str]:
    actual: dict[str, str] = {}
    for path in sorted(rules_root.glob("*.md")):
        if path.name in {"INDEX.md", "COVERAGE.md"}:
            continue
        text = path.read_text(encoding="utf-8")
        for rid in RULE_HEADING_RE.findall(text):
            if rid in actual:
                raise RouteError(f"duplicate canonical Rule ID {rid}: {actual[rid]} and {path.name}")
            actual[rid] = path.name
    expected = {f"R{i:02d}" for i in range(1, 32)}
    ids = set(actual)
    if ids != expected:
        raise RouteError(
            f"canonical Rule coverage mismatch; missing={sorted(expected-ids)}; unknown={sorted(ids-expected)}"
        )
    return actual


def validate_rule_authority(contract: dict) -> tuple[Path, Path, dict[str, str]]:
    index_path = ROOT / contract["rules_index"]
    rules_root = ROOT / contract["rules_root"]
    if not index_path.is_file() or not rules_root.is_dir():
        raise RouteError("rule index or rules root is missing")
    indexed = parse_rule_index(index_path)
    actual = scan_canonical_rules(rules_root)
    if indexed != actual:
        drift = sorted(rid for rid in indexed if indexed.get(rid) != actual.get(rid))
        raise RouteError(f"rules index differs from canonical headings: {drift}")
    return index_path, rules_root, indexed


def resolve_inside_repo(raw: str) -> Path:
    p = Path(raw)
    if not p.is_absolute():
        p = ROOT / p
    p = p.resolve(strict=False)
    try:
        p.relative_to(ROOT.resolve())
    except ValueError as exc:
        raise RouteError(f"target escapes repository: {raw}") from exc
    return p


def posix_rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def _matches_trigger(rel: str, pattern: str) -> bool:
    # A leading **/ denotes zero or more directories. fnmatch/PurePath.match
    # require a slash for this spelling, so also test its zero-directory form.
    while True:
        if fnmatch.fnmatchcase(rel, pattern) or PurePosixPath(rel).match(pattern):
            return True
        if not pattern.startswith('**/'):
            return False
        pattern = pattern[3:]


def matching_capabilities(contract: dict, targets: list[Path]) -> tuple[set[str], list[str]]:
    matched: set[str] = set()
    unmatched: list[str] = []
    triggers = contract.get("triggers", [])
    for target in targets:
        rel = posix_rel(target)
        hit = False
        for trig in triggers:
            cap = trig.get("capability")
            for pattern in trig.get("globs", []):
                if _matches_trigger(rel, pattern):
                    matched.add(cap)
                    hit = True
                    break
        if not hit:
            unmatched.append(rel)
    return matched, unmatched


def capability_closure(contract: dict, requested: set[str]) -> list[str]:
    caps = contract.get("capabilities", {})
    ordered: list[str] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visited:
            return
        if name in visiting:
            raise RouteError(f"capability dependency cycle at {name}")
        spec = caps.get(name)
        if spec is None:
            raise RouteError(f"ROUTE_UNRESOLVED: unknown capability {name}", EXIT_UNRESOLVED)
        if not spec.get("enabled", True):
            raise RouteError(f"ROUTE_UNRESOLVED: capability {name} is reserved but not enabled", EXIT_UNRESOLVED)
        visiting.add(name)
        for dep in spec.get("dependencies", []):
            visit(dep)
        visiting.remove(name)
        visited.add(name)
        ordered.append(name)

    for name in sorted(requested):
        visit(name)
    return ordered


def parse_skill_lock(lock_path: Path) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    cur: dict[str, str] | None = None
    for line in lock_path.read_text(encoding="utf-8").splitlines():
        m = SKILL_ID_RE.match(line)
        if m:
            if cur:
                result[cur["id"]] = cur
            cur = {"id": m.group(1)}
            continue
        if cur:
            cm = COMMIT_RE.match(line)
            if cm:
                cur["commit"] = cm.group(1)
            sm = SKILL_SHA_RE.match(line)
            if sm:
                cur["skill_sha256"] = sm.group(1).lower()
            mm = SKILL_MODE_RE.match(line)
            if mm:
                cur["mode"] = mm.group(1)
    if cur:
        result[cur["id"]] = cur
    return result


def verify_skill(skill_id: str, contract: dict) -> tuple[Path, Path]:
    lock_path = ROOT / contract["skill_lock"]
    if not lock_path.is_file():
        raise RouteError(f"skill lock missing: {posix_rel(lock_path)}")
    skills = parse_skill_lock(lock_path)
    if skill_id not in skills:
        raise RouteError(f"ROUTE_UNRESOLVED: skill is not locked: {skill_id}", EXIT_UNRESOLVED)
    skill_path = ROOT / contract["skill_install_root"] / skill_id / "SKILL.md"
    if not skill_path.is_file():
        raise RouteError(f"ROUTE_UNRESOLVED: locked skill is not installed: {skill_id}", EXIT_UNRESOLVED)
    expected = skills[skill_id].get("commit")
    if expected and expected != "null":
        proc = subprocess.run(
            ["git", "-C", str(skill_path.parent), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0 or proc.stdout.strip() != expected:
            raise RouteError(f"ROUTE_UNRESOLVED: installed skill commit mismatch: {skill_id}", EXIT_UNRESOLVED)
    expected_sha = skills[skill_id].get("skill_sha256")
    if skills[skill_id].get("mode") == "pinned-local" and not expected_sha:
        raise RouteError(f"pinned-local Skill missing sha256: {skill_id}", EXIT_INVALID)
    if expected_sha:
        actual_sha = hashlib.sha256(skill_path.read_bytes()).hexdigest()
        if actual_sha != expected_sha:
            raise RouteError(
                f"ROUTE_UNRESOLVED: installed skill source hash mismatch: {skill_id}",
                EXIT_UNRESOLVED,
            )
    return lock_path, skill_path


def agents_chain(scope: Path) -> list[Path]:
    scope_dir = scope if scope.is_dir() else scope.parent
    rel = scope_dir.relative_to(ROOT)
    chain: list[Path] = []
    cur = ROOT
    for name in ("AGENTS.md", "AGENTS.override.md"):
        p = cur / name
        if p.is_file():
            chain.append(p)
    for part in rel.parts:
        cur = cur / part
        for name in ("AGENTS.md", "AGENTS.override.md"):
            p = cur / name
            if p.is_file():
                chain.append(p)
    seen: set[Path] = set()
    return [p for p in chain if not (p in seen or seen.add(p))]


def add_source(out: list[Source], seen: set[Path], kind: str, path: Path, label: str) -> None:
    path = path.resolve()
    if not path.is_file():
        raise RouteError(f"required route source missing: {path.relative_to(ROOT.resolve())}")
    if path not in seen:
        seen.add(path)
        out.append(Source(kind, path, label))


def build_route(args: argparse.Namespace, contract: dict) -> tuple[list[Source], list[str], list[str], list[str]]:
    index_path, rules_root, indexed = validate_rule_authority(contract)
    phases = contract.get("phases", {})
    requested_phases = args.phase or []
    for phase in requested_phases:
        if phase not in phases:
            raise RouteError(f"ROUTE_UNRESOLVED: unknown phase {phase}", EXIT_UNRESOLVED)

    targets = [resolve_inside_repo(t) for t in (args.target or [])]
    triggered, unmatched = matching_capabilities(contract, targets)
    declared = set(args.capability or [])
    capabilities = capability_closure(contract, triggered | declared)

    if "design" in capabilities:
        from design_contract import validate as validate_design
        errors = validate_design()
        if errors:
            raise RouteError("design contract invalid: " + " | ".join(errors), EXIT_INVALID)

    sources: list[Source] = []
    seen: set[Path] = set()

    scope = resolve_inside_repo(args.scope) if args.scope else ROOT
    include_agents = bool(args.scope)
    include_index = False
    module_names: list[str] = []

    for phase in requested_phases:
        spec = phases[phase]
        include_agents |= spec.get("include_root_agents", False)
        include_index |= spec.get("include_rule_index", False)
        for module in spec.get("modules", []):
            if module not in indexed.values():
                raise RouteError(f"phase {phase} references non-canonical module: {module}")
            if module not in module_names:
                module_names.append(module)

    for cap in capabilities:
        spec = contract["capabilities"][cap]
        for module in spec.get("modules", []):
            if module not in indexed.values():
                raise RouteError(f"capability {cap} references non-canonical module: {module}")
            if module not in module_names:
                module_names.append(module)

    if include_agents:
        for path in agents_chain(scope):
            add_source(sources, seen, "agents", path, posix_rel(path))
    if include_index:
        add_source(sources, seen, "rule-index", index_path, posix_rel(index_path))
    for module in module_names:
        path = rules_root / module
        add_source(sources, seen, "canonical-module", path, module)

    for cap in capabilities:
        spec = contract["capabilities"][cap]
        for raw in spec.get("files", []):
            path = ROOT / raw
            add_source(sources, seen, f"capability:{cap}", path, raw)
        for skill_id in spec.get("skills", []):
            lock, skill = verify_skill(skill_id, contract)
            add_source(sources, seen, "skill-lock", lock, posix_rel(lock))
            add_source(sources, seen, f"skill:{skill_id}", skill, posix_rel(skill))

    if not sources:
        raise RouteError("route set is empty; provide at least one phase, capability, target, or scope")

    return sources, requested_phases, capabilities, unmatched


def unresolved_sources(sources: list[Source], contract: dict, capabilities: list[str]) -> list[str]:
    unresolved: list[str] = []
    by_path = {s.path.resolve(): s for s in sources}
    for cap in capabilities:
        spec = contract["capabilities"][cap]
        status_regex = spec.get("status_regex")
        if not status_regex:
            continue
        resolved_values = set(spec.get("resolved_values", ["RESOLVED"]))
        checked = False
        # Only entrypoint files carry a RESOLVED status. Full normative sources
        # are still emitted and hashed by build_route; they need no status line.
        for raw in spec.get("status_files", spec.get("files", [])):
            path = (ROOT / raw).resolve()
            if path not in by_path:
                continue
            checked = True
            text = path.read_text(encoding="utf-8")
            match = re.search(status_regex, text, re.MULTILINE)
            if not match or match.group(1) not in resolved_values:
                unresolved.append(cap)
                break
        if not checked:
            unresolved.append(cap)
    return unresolved


def emit(sources: list[Source], phases: list[str], capabilities: list[str], unmatched: list[str]) -> None:
    print("===== APCF ROUTE PLAN =====")
    print("policy: recall-first")
    print("phases: " + (", ".join(phases) if phases else "none"))
    print("capabilities: " + (", ".join(capabilities) if capabilities else "none"))
    if unmatched:
        print("coverage-notice: targets with no deterministic capability trigger: " + ", ".join(unmatched))
        print("coverage-notice: declare semantic capabilities explicitly; post-route audit is not part of Step 1B")
    print("sources:")
    for s in sources:
        print(f"- {s.kind}: {posix_rel(s.path)}")
    print("===== APCF ROUTE PLAN END =====")
    for s in sources:
        rel = posix_rel(s.path)
        print(f"\n===== APCF ROUTE SOURCE BEGIN | {s.kind} | {rel} =====")
        text = s.path.read_text(encoding="utf-8")
        print(text, end="" if text.endswith("\n") else "\n")
        print(f"===== APCF ROUTE SOURCE END | {s.kind} | {rel} =====")


def main() -> int:
    ap = argparse.ArgumentParser(description="Resolve and emit current APCF routing context")
    ap.add_argument("--phase", action="append", help="Routing phase; repeatable")
    ap.add_argument("--capability", action="append", help="Explicit semantic capability; repeatable")
    ap.add_argument("--target", action="append", help="Target path used for deterministic capability triggers; repeatable")
    ap.add_argument("--scope", help="Repository path used to recompute nested AGENTS.md chain")
    ap.add_argument(
        "--turn-dir",
        help="Current main TR directory; when provided, append a successful routing receipt under evidence/routing.jsonl",
    )
    args = ap.parse_args()
    try:
        contract = load_contract()
        if args.turn_dir:
            validate_turn_dir(args.turn_dir)
        authority_rows = authority_snapshot()
        sources, phases, capabilities, unmatched = build_route(args, contract)
        source_rows = source_snapshot(sources)
        emit(sources, phases, capabilities, unmatched)
        sys.stdout.flush()
        verify_snapshot_rows(source_rows, "source")
        verify_snapshot_rows(authority_rows, "authority")
        unresolved = unresolved_sources(sources, contract, capabilities)
        if unresolved:
            print("ROUTE_UNRESOLVED: capability entrypoints are not resolved: " + ", ".join(unresolved))
            return EXIT_UNRESOLVED
        if args.turn_dir:
            path, receipt = record_route_receipt(
                turn_dir_raw=args.turn_dir,
                phases=phases,
                declared_capabilities=list(args.capability or []),
                resolved_capabilities=capabilities,
                targets=[posix_rel(resolve_inside_repo(t)) for t in (args.target or [])],
                scope=posix_rel(resolve_inside_repo(args.scope)) if args.scope else ".",
                unmatched_targets=unmatched,
                sources=sources,
                source_rows=source_rows,
                authority_rows=authority_rows,
            )
            print(
                "receipt: recorded; "
                f"id={receipt['receipt_id']}; path={posix_rel(path)}; fingerprint={receipt['route_fingerprint']}"
            )
        else:
            print("receipt: not recorded; no --turn-dir supplied (Step 1C does not enforce receipt usage yet)")
        print("PASS: route context resolved and emitted")
        return 0
    except (RouteError, ReceiptError) as exc:
        print(f"FAIL: {exc}")
        return exc.code
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        print(f"FAIL: route context I/O or parse error: {exc}")
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
