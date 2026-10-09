# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import argparse
import hashlib
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STD = ROOT / ".agent-project-control" / "standards"
FW = ROOT / ".agent-project-control"
W = ".agent-project-control/standards/human-readable-chinese-writing-v0.1.md"
S = ".agent-project-control/standards/human-readable-chinese-style-v0.1.md"
META = '<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'


def _lock() -> dict[str, str]:
    result: dict[str, str] = {}
    for line in (STD / "LOCK.yaml").read_text(encoding="utf-8").splitlines():
        if line.startswith("#") or not line.strip():
            continue
        if ": " in line:
            key, value = line.split(": ", 1)
            result[key] = value.strip()
    return result


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> list[str]:
    problems: list[str] = []
    try:
        lock = _lock()
        if lock.get("schema") != "1" or lock.get("version") != "v0.1":
            problems.append("standards LOCK.yaml wrong schema/version")
        for key, rel in (("writing", W), ("style", S)):
            if lock.get(f"{key}_path") != rel:
                problems.append(f"{key} source path mismatch in LOCK")
            path = ROOT / rel
            if not path.is_file():
                problems.append(f"missing {key} source: {rel}")
            elif lock.get(f"{key}_sha256") != _sha(path):
                problems.append(f"{key} source changed without updating standards LOCK.yaml")
        if not (STD / ".apcf-dir.yaml").is_file():
            problems.append("missing standards directory visibility marker")
        if (ROOT / W).is_file():
            text = (ROOT / W).read_text(encoding="utf-8")
            if not text.startswith(META):
                problems.append("writing source metadata missing")
            headings = {int(i) for i in re.findall(r"^## (\d+)\. ", text, re.M)}
            if headings != set(range(1, 30)):
                problems.append("writing rule coverage is not 1–29")
            if not all(f"**{section}**" in text for section in ("原则", "触发", "必须", "例外")):
                problems.append("writing mandatory rule section missing")
        if (ROOT / S).is_file():
            text = (ROOT / S).read_text(encoding="utf-8")
            if not text.startswith(META):
                problems.append("style source metadata missing")
            headings = re.findall(r"^## (S\d{2})\. ", text, re.M)
            if headings != [f"S{i:02d}" for i in range(15)]:
                problems.append("style rule coverage is not S00–S14")
            if "v31" in text or "v1.4" in text or "candidate" in text:
                problems.append("style contains obsolete version reference")
        writing_if = FW / "interfaces/WRITING_STANDARD.md"
        style_if = FW / "interfaces/STYLE_STANDARD.md"
        for name, path, rel in (("writing", writing_if, W), ("style", style_if, S)):
            if not path.is_file():
                problems.append(f"{name} interface missing")
                continue
            text = path.read_text(encoding="utf-8")
            for marker in ("- **状态**：`RESOLVED`", "- **正式版本**：`v0.1`", f"`{rel}`"):
                if marker not in text:
                    problems.append(f"{name} interface missing marker: {marker}")
        with (FW / "routing.toml").open("rb") as f:
            route = tomllib.load(f)
        caps = route["capabilities"]
        if set(caps["human-readable"].get("dependencies", [])) != {"writing", "style"}:
            problems.append("human-readable does not depend on both writing and style")
        for cap, source, interface in (("writing",W,".agent-project-control/interfaces/WRITING_STANDARD.md"),("style",S,".agent-project-control/interfaces/STYLE_STANDARD.md")):
            cfg = caps.get(cap, {})
            if not cfg.get("enabled", False):
                problems.append(f"{cap} capability disabled")
            if not {source, interface}.issubset(set(cfg.get("files", []))):
                problems.append(f"{cap} does not route interface and full source")
            if cfg.get("status_files") != [interface]:
                problems.append(f"{cap} status_files must name only its interface")
        triggers = route.get("triggers", [])
        if not any(t.get("capability") == "human-readable" for t in triggers):
            problems.append("human-readable deterministic triggers missing")
    except (OSError, ValueError, KeyError, tomllib.TOMLDecodeError) as exc:
        problems.append(f"standards contract could not be validated: {exc}")
    return problems


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--check", action="store_true")
    p.parse_args()
    problems = validate()
    if problems:
        for problem in problems:
            print("FAIL:",problem)
        return 2
    print("PASS: Writing v0.1 + Style v0.1 source, interfaces, versions and router are consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
