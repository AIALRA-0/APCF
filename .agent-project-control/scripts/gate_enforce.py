# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

from gate_check import evaluate_route_gate
from gate_kernel import GateError, load_gate_contract, validate_turn_dir

ROOT = Path(__file__).resolve().parents[2]
FRAMEWORK_ROOT = ROOT / ".agent-project-control"
ROUTER = FRAMEWORK_ROOT / "scripts" / "route_context.py"

EXIT_INVALID = 2


class EnforcementError(RuntimeError):
    def __init__(self, message: str, code: int = EXIT_INVALID):
        super().__init__(message)
        self.code = code


def load_entrypoint(name: str) -> dict:
    contract = load_gate_contract()
    entrypoints = contract.get("entrypoints")
    if not isinstance(entrypoints, dict):
        raise EnforcementError("gate contract missing entrypoints")
    spec = entrypoints.get(name)
    if not isinstance(spec, dict):
        raise EnforcementError(f"unknown enforcement entrypoint: {name}")

    gate = spec.get("gate")
    if not isinstance(gate, bool):
        raise EnforcementError(f"entrypoint {name} missing boolean gate")

    auto = spec.get("auto_route_phases", [])
    required = spec.get("required_phases", [])
    for label, value in (("auto_route_phases", auto), ("required_phases", required)):
        if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
            raise EnforcementError(f"entrypoint {name} has invalid {label}")

    for key in ("require_workflow", "require_acceptance", "require_content"):
        if key in spec and not isinstance(spec[key], bool):
            raise EnforcementError(f"entrypoint {name} has invalid {key}")
    capabilities = spec.get("required_capabilities", [])
    if not isinstance(capabilities, list) or any(
        not isinstance(x, str) or not x.strip() for x in capabilities
    ):
        raise EnforcementError(f"entrypoint {name} has invalid required_capabilities")

    if gate:
        for key in ("profile", "gate_id"):
            if not isinstance(spec.get(key), str) or not spec[key].strip():
                raise EnforcementError(f"entrypoint {name} missing {key}")
    return spec


def _route_phase(turn_dir: Path, phase: str) -> None:
    cmd = [
        sys.executable,
        "-B",
        str(ROUTER),
        "--phase",
        phase,
        "--turn-dir",
        str(turn_dir),
    ]
    # Do not capture stdout/stderr. The route source bodies must remain visible to
    # the calling Agent, and route_context owns the Receipt write.
    # The resolved script path can exceed Windows MAX_PATH inside nested runtime
    # fixtures. Python may then leave sys.path[0] empty, so make this child's
    # sibling imports explicit without changing the caller's environment.
    env = os.environ.copy()
    inherited_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = os.pathsep.join(
        [str(ROUTER.parent)] + ([inherited_pythonpath] if inherited_pythonpath else [])
    )
    proc = subprocess.run(cmd, cwd=ROOT, env=env)
    if proc.returncode != 0:
        raise EnforcementError(
            f"automatic route failed for phase '{phase}' with exit code {proc.returncode}",
            proc.returncode if proc.returncode in {2, 3} else EXIT_INVALID,
        )


def _print_denial(entrypoint: str, record: dict) -> None:
    print(
        f"GATE_DENIED: entrypoint={entrypoint}; result={record['result']}; "
        f"attempt_id={record['attempt_id']}; transition={record['transition']['kind']}"
    )
    if record["result"] == "NO_PROGRESS":
        reason = record.get("transition", {}).get("no_progress_reason")
        if reason:
            print(f"NO_PROGRESS_REASON: {reason}")
    repairs = record.get("repair_set", [])
    if repairs:
        print("REPAIR_SET:")
        for repair in repairs:
            scope = ",".join(repair.get("scope", [])) or "."
            print(
                f"- {repair['repair_id']} | {repair['kind']} | target={repair['target']} | "
                f"scope={scope}"
            )
            print(f"  action: {repair['instruction']}")
            print(f"  verify: {repair['verification']}")
    blocked = [f for f in record.get("findings", []) if f.get("repairability") == "blocked"]
    if blocked:
        print("BLOCKED_FINDINGS:")
        for finding in blocked:
            print(f"- {finding['finding_id']} | {finding['code']} | {finding['subject']}")
            print(f"  reason: {finding['message']}")


def enforce_entrypoint(
    *,
    entrypoint: str,
    turn_dir_raw: str | Path,
    targets: list[str] | None = None,
    before_gate: Callable[[Path], None] | None = None,
) -> tuple[int, dict | None]:
    turn_dir = validate_turn_dir(turn_dir_raw)
    spec = load_entrypoint(entrypoint)

    if entrypoint == "action":
        if not targets or any(not isinstance(target, str) or not target.strip() for target in targets):
            raise EnforcementError("action entrypoint requires one or more non-empty --target values")
        if len(set(targets)) != len(targets):
            raise EnforcementError("action entrypoint has duplicate --target values")

    # Known framework entrypoints route their mandatory phase before action. This
    # is deterministic pre-routing, not an Agent retry loop.
    for phase in spec.get("auto_route_phases", []):
        _route_phase(turn_dir, phase)

    if not spec["gate"]:
        return 0, None

    # A caller such as finalize_turn can capture its immutable pre-Gate candidate
    # after deterministic routing has written its Receipts, without making a
    # second Gate attempt.
    if before_gate is not None:
        before_gate(turn_dir)

    code, record = evaluate_route_gate(
        turn_dir_raw=str(turn_dir),
        gate_id=spec["gate_id"],
        phases=list(spec.get("required_phases", [])),
        capabilities=list(spec.get("required_capabilities", [])),
        semantic_reviewed=False,
        unresolved=[],
        profile=spec["profile"],
        action_targets=targets,
        require_target_routes=entrypoint == "action",
        require_workflow=bool(spec.get("require_workflow", False)),
        require_acceptance=bool(spec.get("require_acceptance", False)),
        acceptance_stage="publish" if entrypoint == "publish" else "final",
        require_content=bool(spec.get("require_content", False)),
    )
    if code != 0:
        _print_denial(entrypoint, record)
    return code, record


def _in_progress_turns() -> list[Path]:
    result: list[Path] = []
    iterations = FRAMEWORK_ROOT / "iterations"
    if not iterations.is_dir():
        return result
    for turn in iterations.glob("IT-*/turns/TR-*"):
        f = turn / "TURN.md"
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        if "**Status**：IN_PROGRESS" in text:
            result.append(turn.resolve())
    return sorted(result)


def _turn_from_current() -> Path | None:
    current = ROOT / "CURRENT.md"
    if not current.is_file():
        return None
    try:
        text = current.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None
    match = re.search(r"^- \*\*Source TURN\*\*：`([^`]+)`", text, flags=re.MULTILINE)
    if not match:
        return None
    candidate = (ROOT / match.group(1)).resolve()
    try:
        return validate_turn_dir(candidate)
    except GateError:
        return None


def resolve_delivery_turn(turn_dir_raw: str | Path | None) -> Path:
    if turn_dir_raw:
        return validate_turn_dir(turn_dir_raw)

    active = _in_progress_turns()
    if len(active) == 1:
        return validate_turn_dir(active[0])
    if len(active) > 1:
        raise EnforcementError(
            "delivery Turn is ambiguous: multiple IN_PROGRESS TRs exist; pass --turn-dir explicitly"
        )

    current = _turn_from_current()
    if current is not None:
        return current
    raise EnforcementError(
        "cannot resolve delivery Turn from an IN_PROGRESS TR or CURRENT.md; pass --turn-dir explicitly"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="APCF Gate enforcement controller")
    ap.add_argument("--entrypoint", required=True, choices=["bootstrap", "parallel", "action", "finalize", "publish"])
    ap.add_argument("--turn-dir")
    ap.add_argument("--target", action="append", dest="targets")
    ap.add_argument("--run", nargs=argparse.REMAINDER, help="command to run once after an action Gate PASS")
    args = ap.parse_args()

    try:
        if args.entrypoint == "publish":
            turn_dir = resolve_delivery_turn(args.turn_dir)
        elif args.turn_dir:
            turn_dir = validate_turn_dir(args.turn_dir)
        else:
            raise EnforcementError(f"{args.entrypoint} requires --turn-dir")

        run_args = list(args.run or [])
        if run_args[:1] == ["--"]:
            run_args = run_args[1:]
        if args.entrypoint == "action" and not run_args:
            raise EnforcementError("action entrypoint requires --run COMMAND [ARGS...]")
        if args.entrypoint != "action" and args.run is not None:
            raise EnforcementError("--run is supported only with the action entrypoint")

        code, record = enforce_entrypoint(
            entrypoint=args.entrypoint,
            turn_dir_raw=turn_dir,
            targets=list(args.targets) if args.targets is not None else None,
        )
        if code == 0:
            if record is None:
                print(f"PASS: entrypoint={args.entrypoint}; mandatory pre-route completed")
            else:
                print(
                    f"PASS: entrypoint={args.entrypoint}; gate_id={record['gate_id']}; "
                    f"attempt_id={record['attempt_id']}"
                )
            if args.entrypoint == "action":
                # This is a single, explicit argv execution after Gate PASS. It is
                # not a general shell-interception mechanism.
                return subprocess.run(run_args, cwd=ROOT, shell=False).returncode
        return code
    except (GateError, EnforcementError) as exc:
        print(f"FAIL: {exc}")
        return getattr(exc, "code", EXIT_INVALID)
    except Exception as exc:
        print(f"FAIL: enforcement internal error: {exc}")
        return EXIT_INVALID


if __name__ == "__main__":
    raise SystemExit(main())
