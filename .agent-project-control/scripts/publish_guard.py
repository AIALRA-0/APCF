# APCF-META {"schema":1,"visibility":"public"}
import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import tempfile
import unicodedata
import zipfile
from pathlib import Path

from common import ROOT, FRAMEWORK_ROOT, meta_line
from gate_kernel import GateError
from gate_enforce import EnforcementError, enforce_entrypoint, resolve_delivery_turn
from state_integrity import validate as validate_state


RUNTIME_SCAFFOLD = {
    ".agent-project-control/runtime/.apcf-dir.yaml",
    *{
        f".agent-project-control/runtime/{name}/.apcf-dir.yaml"
        for name in ("testbed", "runs", "downloads", "tmp", "cache", "large", "distribution")
    },
}
MANAGED_ROOT_FILES = {"AGENTS.md", "CURRENT.md", ".apcf-dir.yaml"}
OPERATIONAL_INDEXES = {
    ".agent-project-control/iterations": "IT|TR",
    ".agent-project-control/regressions": "REG",
    ".agent-project-control/decisions": "ADR",
    ".agent-project-control/runbooks": "RB",
    ".agent-project-control/materials": "MAT",
}
RUNTIME_ALLOWED = RUNTIME_SCAFFOLD

TEXT_META_RE = re.compile(r"^<!-- APCF-META\s+(\{.*?\})\s+-->$")
COMMENT_META_RE = re.compile(r"^# APCF-META\s+(\{.*?\})$")
SOURCE_RE = re.compile(r"^- \*\*Source TURN\*\*：`([^`]+)`", re.MULTILINE)
YAML_SCALAR_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z][A-Za-z0-9_-]*)\s*:\s*(?:\"(?P<double>[^\"]*)\"|'(?P<single>[^']*)'|(?P<plain>[^\s#]+))\s*(?:#.*)?$"
)
YAML_DIGEST_RE = re.compile(
    r"^\s*(?P<key>[A-Za-z][A-Za-z0-9_-]*_sha256)\s*:\s*(?:\"(?P<double>[0-9a-fA-F]{64})\"|'(?P<single>[0-9a-fA-F]{64})'|(?P<plain>[0-9a-fA-F]{64}))\s*$"
)

PRIVATE_WINDOWS_HOME = re.compile(
    rb"(?i)(?<![A-Za-z0-9])(?P<drive>[A-Z]:\\)(?:Users|Documents and Settings)\\(?P<user>[^\\/\s<>:\"|?*]+)(?:\\[^\r\n\"<>]*)?"
)
PRIVATE_WORKSPACE = re.compile(
    rb"(?i)(?<![A-Za-z0-9])[A-Z]:\\(?:[^\\\r\n\"<>]*\\)*AIALRA(?: Codex Workspace)?\\[^\r\n\"<>]*"
)
PRIVATE_UNIX_HOME = re.compile(
    rb"(?i)(?<![A-Za-z0-9])/(?:home|Users)/(?P<user>[^/\s<>]+)(?:/[^\r\n\"<>]*)?"
)
PRIVATE_UNC = re.compile(
    rb"(?<!\\)\\\\(?P<host>[^\\/\s<>]+)\\(?P<share>[^\\/\s<>]+)(?:\\[^\r\n\"<>]*)?"
)
PRIVATE_EMAIL = re.compile(
    rb"(?i)(?<![A-Za-z0-9._%+-])[A-Z0-9._%+-]+@(?P<domain>[A-Z0-9.-]+\.[A-Z]{2,})(?![A-Za-z0-9.-])"
)
SECRET_ASSIGNMENT = re.compile(
    rb"(?i)\b(?P<key>password|passwd|pwd|token|api[_-]?key|secret|client[_-]?secret|access[_-]?key|pat)\b\s*[:=]\s*(?![A-Za-z][A-Za-z0-9_-]*\s*[:=])(?P<value>\"[^\"]*\"|'[^']*'|[^\"'\s,;\}\]]+)"
)
CREDENTIAL_URL = re.compile(
    rb"(?i)\b[a-z][a-z0-9+.-]*://(?P<user>[^:/@\s]+):(?P<password>[^@\s/]+)@(?P<host>[^/:?#\s]+)"
)


class PublishScanError(Exception):
    pass


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


def _safe_rel(raw: str) -> str:
    if not isinstance(raw, str) or not raw or "\\" in raw or raw.startswith("/"):
        raise PublishScanError("unsafe candidate-relative path")
    if re.match(r"^[A-Za-z]:", raw):
        raise PublishScanError("unsafe candidate-relative path")
    parts = raw.split("/")
    invalid_chars = set('<>:"|?*')
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in parts:
        if part in {"", ".", ".."} or part.endswith((".", " ")):
            raise PublishScanError("unsafe candidate-relative path")
        if any(ord(ch) < 32 or 0xD800 <= ord(ch) <= 0xDFFF or ch in invalid_chars for ch in part):
            raise PublishScanError("unsafe candidate-relative path")
        if part.split(".", 1)[0].upper() in reserved:
            raise PublishScanError("unsafe candidate-relative path")
    return raw


def _validate_file_paths(paths) -> None:
    """Reject file names that alias on the Windows candidate materializer."""
    canonical = {}
    for raw in paths:
        rel = _safe_rel(raw)
        key = tuple(unicodedata.normalize("NFC", part).casefold() for part in rel.split("/"))
        previous = canonical.get(key)
        if previous is not None and previous != rel:
            raise PublishScanError(f"candidate paths collide on a case-insensitive filesystem: {rel}")
        canonical[key] = rel
    for key, rel in canonical.items():
        for length in range(1, len(key)):
            prefix = key[:length]
            if prefix in canonical:
                raise PublishScanError(f"candidate file/directory paths conflict: {rel}")


def _candidate_git_env() -> dict:
    env = os.environ.copy()
    for key in tuple(env):
        if key.startswith("GIT_"):
            env.pop(key, None)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def _git_bytes(repo: Path, *args: str, candidate: bool = False) -> bytes:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            cwd=ROOT,
            capture_output=True,
            env=_candidate_git_env() if candidate else None,
        )
    except OSError as exc:
        raise PublishScanError("Git could not read the requested index object") from exc
    if result.returncode:
        raise PublishScanError("Git could not read the requested index object")
    return result.stdout


def _index_entries(repo: Path, *, candidate: bool) -> dict:
    raw = _git_bytes(repo, "ls-files", "--stage", "-z", candidate=candidate)
    entries = {}
    for record in raw.split(b"\0"):
        if not record:
            continue
        try:
            header, raw_path = record.split(b"\t", 1)
            mode, oid, stage = header.decode("ascii").split(" ")
            rel = _safe_rel(raw_path.decode("utf-8"))
        except (ValueError, UnicodeError, PublishScanError) as exc:
            raise PublishScanError("Git index contains an invalid or unreadable path entry") from exc
        if rel in entries:
            raise PublishScanError(f"Git index contains multiple stages for {rel}")
        if stage != "0":
            raise PublishScanError(f"Git index contains an unmerged object for {rel}")
        if mode not in {"100644", "100755"}:
            raise PublishScanError(f"Git index has an unsupported object type for {rel}")
        if not re.fullmatch(r"[0-9a-fA-F]{40}|[0-9a-fA-F]{64}", oid):
            raise PublishScanError(f"Git index has an invalid object id for {rel}")
        entries[rel] = {"mode": mode, "oid": oid}
    return entries


def _blob(repo: Path, oid: str, *, candidate: bool) -> bytes:
    object_type = _git_bytes(repo, "cat-file", "-t", oid, candidate=candidate).strip()
    if object_type != b"blob":
        raise PublishScanError("Git index entry does not identify a blob")
    return _git_bytes(repo, "cat-file", "blob", oid, candidate=candidate)


def _name_status(repo: Path, *, candidate: bool) -> list:
    raw = _git_bytes(repo, "diff", "--cached", "--name-status", "-z", candidate=candidate)
    parts = raw.split(b"\0")
    records = []
    i = 0
    while i < len(parts) and parts[i]:
        try:
            status = parts[i].decode("ascii")
        except UnicodeError as exc:
            raise PublishScanError("Git index change status is unreadable") from exc
        i += 1
        count = 2 if status[:1] in {"R", "C"} else 1
        if i + count > len(parts):
            raise PublishScanError("Git index change record is incomplete")
        paths = []
        for raw_path in parts[i:i + count]:
            try:
                paths.append(_safe_rel(raw_path.decode("utf-8")))
            except (UnicodeError, PublishScanError) as exc:
                raise PublishScanError("Git index change contains an invalid path") from exc
        i += count
        records.append((status, paths))
    return records


def _parse_meta(payload: bytes):
    try:
        first = payload.splitlines()[0].decode("utf-8")
    except (IndexError, UnicodeError):
        return None
    for pattern in (TEXT_META_RE, COMMENT_META_RE):
        match = pattern.match(first)
        if match:
            try:
                value = json.loads(match.group(1))
            except (json.JSONDecodeError, TypeError):
                return None
            return value if isinstance(value, dict) else None
    return None


def _is_managed(rel: str) -> bool:
    return rel.startswith(".agent-project-control/") or rel in MANAGED_ROOT_FILES


def _metadata_errors(rel: str, entries: dict, get_blob) -> list:
    if not _is_managed(rel):
        return []
    errors = []
    try:
        payload = get_blob(rel)
    except (KeyError, PublishScanError):
        return [f"{rel}: staged object is unreadable"]
    meta = _parse_meta(payload)
    if rel in RUNTIME_SCAFFOLD:
        # These eight empty-directory markers describe the private lifecycle
        # area; they contain no private execution material. No other runtime
        # object, extra field, comment or payload is covered by this exception.
        try:
            lines = payload.decode("utf-8").splitlines()
        except UnicodeError:
            lines = []
        if (meta == {"schema": 1, "visibility": "private"}
                and len(lines) == 3
                and lines[1:] == ["schema: 1", "visibility: private"]):
            return []
        return [f"{rel}: runtime scaffold must contain only private schema-1 metadata"]
    sidecar_path = rel + ".apcf-meta.yaml"
    sidecar_entry = entries.get(sidecar_path)
    sidecar_meta = None
    if sidecar_entry is not None:
        try:
            sidecar = get_blob(sidecar_path)
        except (KeyError, PublishScanError):
            return [f"{sidecar_path}: staged metadata is unreadable"]
        sidecar_meta = _parse_meta(sidecar)
        expected = b"sha256: " + hashlib.sha256(payload).hexdigest().encode("ascii")
        if expected not in sidecar.splitlines():
            errors.append(f"{rel}: staged companion metadata digest mismatch")
    if meta is None:
        meta = sidecar_meta
    if not meta or meta.get("schema") != 1 or meta.get("visibility") not in {"public", "private"}:
        errors.append(f"{rel}: staged visibility metadata missing or invalid")
    elif meta.get("visibility") == "private":
        errors.append(f"{rel}: private object staged")
    if sidecar_meta and sidecar_meta.get("visibility") == "private":
        errors.append(f"{sidecar_path}: private metadata staged")
    return errors


def _source_stage_errors() -> list:
    errors = []
    try:
        entries = _index_entries(ROOT, candidate=False)
        changes = _name_status(ROOT, candidate=False)
    except PublishScanError as exc:
        return ["source Git index: " + str(exc)]

    def get_blob(rel: str) -> bytes:
        entry = entries[rel]
        return _blob(ROOT, entry["oid"], candidate=False)

    staged = []
    for status, paths in changes:
        if status.startswith("D"):
            continue
        rel = paths[-1]
        if rel in entries:
            staged.append(rel)
    for rel in sorted(set(staged)):
        if rel.startswith(".agent-project-control/runtime/") and rel not in RUNTIME_SCAFFOLD:
            errors.append(f"{rel}: runtime artifact staged")
            continue
        errors.extend(_metadata_errors(rel, entries, get_blob))
    return errors


def _manifest(path: Path, candidate_root: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise PublishScanError("manifest is unreadable")
    resolved = path.resolve()
    if _is_within(resolved, candidate_root):
        raise PublishScanError("manifest must remain outside the candidate Git repository")
    try:
        data = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishScanError("manifest is unreadable or invalid JSON") from exc
    if not isinstance(data, dict) or set(data) != {"schema", "visibility", "files"}:
        raise PublishScanError("manifest schema is invalid")
    if data.get("schema") != 1 or data.get("visibility") != "private" or not isinstance(data.get("files"), list):
        raise PublishScanError("manifest must be a private schema-1 inventory")
    files = {}
    for row in data["files"]:
        if not isinstance(row, dict) or set(row) != {"path", "bytes", "sha256"}:
            raise PublishScanError("manifest file entry is invalid")
        try:
            rel = _safe_rel(row["path"])
        except PublishScanError as exc:
            raise PublishScanError("manifest contains an unsafe relative path") from exc
        size = row["bytes"]
        digest = row["sha256"]
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PublishScanError(f"manifest byte count is invalid for {rel}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise PublishScanError(f"manifest SHA-256 is invalid for {rel}")
        if rel in files:
            raise PublishScanError(f"manifest repeats {rel}")
        files[rel] = {"bytes": size, "sha256": digest}
    if not files:
        raise PublishScanError("manifest contains no candidate files")
    _validate_file_paths(files)
    return files


def _materialize_index(repo: Path, entries: dict, payload_root: Path, expected: dict) -> dict:
    _validate_file_paths(entries)
    payload_root.mkdir(parents=True, exist_ok=True)
    records = {}
    for rel, entry in sorted(entries.items()):
        if rel not in expected:
            raise PublishScanError(f"candidate Git index contains an unapproved object: {rel}")
        try:
            indexed_size = int(_git_bytes(repo, "cat-file", "-s", entry["oid"], candidate=True).strip())
        except (ValueError, PublishScanError) as exc:
            raise PublishScanError(f"candidate Git index object size is unreadable: {rel}") from exc
        if indexed_size != expected[rel]["bytes"]:
            raise PublishScanError(f"candidate Git index object size differs from manifest: {rel}")
        data = _blob(repo, entry["oid"], candidate=True)
        digest = hashlib.sha256(data).hexdigest()
        if len(data) != indexed_size:
            raise PublishScanError(f"candidate Git index object is truncated: {rel}")
        target = payload_root.joinpath(*rel.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            target.write_bytes(data)
        except OSError as exc:
            raise PublishScanError(f"candidate index object could not be materialized: {rel}") from exc
        records[rel] = {"bytes": len(data), "sha256": digest, "file": target}
        del data
    return records


def _check_inventory(label: str, actual: dict, expected: dict) -> list:
    errors = []
    for rel in sorted(set(expected) - set(actual)):
        errors.append(f"{label} is missing manifest object: {rel}")
    for rel in sorted(set(actual) - set(expected)):
        errors.append(f"{label} contains an unapproved object: {rel}")
    for rel in sorted(set(actual) & set(expected)):
        if actual[rel]["bytes"] != expected[rel]["bytes"] or actual[rel]["sha256"] != expected[rel]["sha256"]:
            errors.append(f"{label} bytes or SHA-256 differ from manifest: {rel}")
    return errors


def _zip_payload(zip_path: Path, payload_root: Path, expected: dict) -> dict:
    if zip_path.is_symlink() or not zip_path.is_file():
        raise PublishScanError("candidate ZIP is unreadable")
    payload_root.mkdir(parents=True, exist_ok=True)
    records = {}
    directories = set()
    try:
        archive = zipfile.ZipFile(zip_path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise PublishScanError("candidate ZIP cannot be opened") from exc
    with archive:
        for info in archive.infolist():
            name = info.filename
            is_dir = info.is_dir()
            if is_dir:
                if not name.endswith("/") or name.endswith("//"):
                    raise PublishScanError("candidate ZIP contains a malformed directory member")
                raw_rel = name[:-1]
            else:
                raw_rel = name
            try:
                rel = _safe_rel(raw_rel)
            except PublishScanError as exc:
                raise PublishScanError("candidate ZIP contains an unsafe member path") from exc
            if not is_dir:
                if rel not in expected:
                    raise PublishScanError(f"candidate ZIP contains an unapproved member: {rel}")
                if info.file_size != expected[rel]["bytes"]:
                    raise PublishScanError(f"candidate ZIP member size differs from manifest: {rel}")
            mode = (info.external_attr >> 16) & 0xFFFF
            if stat.S_ISLNK(mode):
                raise PublishScanError(f"candidate ZIP contains a symbolic link: {rel}")
            if stat.S_ISDIR(mode) and not is_dir:
                raise PublishScanError(f"candidate ZIP contains a malformed directory member: {rel}")
            if info.flag_bits & 0x1:
                raise PublishScanError(f"candidate ZIP member is encrypted: {rel}")
            if is_dir:
                if rel in directories or rel in records:
                    raise PublishScanError(f"candidate ZIP repeats a member: {rel}")
                directories.add(rel)
                continue
            if rel in records or rel in directories:
                raise PublishScanError(f"candidate ZIP repeats a member: {rel}")
            target = payload_root.joinpath(*rel.split("/"))
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            size = 0
            try:
                with archive.open(info, "r") as source, target.open("wb") as destination:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        if size + len(chunk) > expected[rel]["bytes"]:
                            raise PublishScanError(f"candidate ZIP member exceeds manifest byte count: {rel}")
                        size += len(chunk)
                        digest.update(chunk)
                        destination.write(chunk)
            except (OSError, RuntimeError, zipfile.BadZipFile, zipfile.LargeZipFile) as exc:
                raise PublishScanError(f"candidate ZIP member cannot be read: {rel}") from exc
            if size != info.file_size:
                raise PublishScanError(f"candidate ZIP member size is inconsistent: {rel}")
            records[rel] = {"bytes": size, "sha256": digest.hexdigest(), "file": target}
    files = set(records)
    for directory in directories:
        if not any(rel.startswith(directory + "/") for rel in files):
            raise PublishScanError(f"candidate ZIP contains an unapproved empty directory: {directory}")
        if directory in files:
            raise PublishScanError(f"candidate ZIP path is both file and directory: {directory}")
    return records


def _placeholder_value(value: bytes) -> bool:
    normalized = value.strip().strip(b"\"'`<> ").lower()
    if not normalized or normalized in {b"null", b"none", b"nil", b"undefined", b"example.invalid"}:
        return True
    if normalized.startswith((b"${", b"$env:", b"os.environ", b"process.env", b"getenv(")):
        return True
    if value.strip().startswith(b"<") and value.strip().endswith(b">"):
        return True
    return False


def _python_code_context(record: dict):
    """Return AST-backed context for Python objects, or None when unprovable."""
    path = record["file"]
    if path.suffix.lower() != ".py":
        return None
    try:
        payload = path.read_bytes()
        tree = ast.parse(payload.decode("utf-8"))
    except (OSError, UnicodeError, SyntaxError):
        return None
    parents = {}
    nodes = list(ast.walk(tree))
    for node in nodes:
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    line_starts = [0]
    for line in payload.splitlines(keepends=True):
        line_starts.append(line_starts[-1] + len(line))
    if line_starts[-1] < len(payload):
        line_starts.append(len(payload))

    def span(node):
        if not all(hasattr(node, name) for name in ("lineno", "col_offset", "end_lineno", "end_col_offset")):
            return None
        if node.lineno < 1 or node.end_lineno < node.lineno or node.end_lineno >= len(line_starts) + 1:
            return None
        return line_starts[node.lineno - 1] + node.col_offset, line_starts[node.end_lineno - 1] + node.end_col_offset

    def bytes_value(value):
        if isinstance(value, bytes):
            return value
        if isinstance(value, str):
            return value.encode("utf-8", errors="strict")
        return None

    def re_compile_call(node):
        return (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "compile"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "re"
        )

    def sensitive_literal(value: bytes) -> bool:
        if any(regex.search(value) for regex in (PRIVATE_WINDOWS_HOME, PRIVATE_WORKSPACE, PRIVATE_UNIX_HOME)):
            return True
        regex_syntax = (b"(", b")", b"[", b"]", bytes([92]))
        generic_unc = {b"user", b"username", b"name", b"account", b"server", b"host", b"hostname", b"share", b"sharename"}
        for match in PRIVATE_UNC.finditer(value):
            host, share = match.group("host").lower(), match.group("share").lower()
            if not (any(marker in host + share for marker in regex_syntax) or host in generic_unc or share in generic_unc):
                return True
        if any(not match.group("domain").lower().endswith(b".invalid") for match in PRIVATE_EMAIL.finditer(value)):
            return True
        if any(not _placeholder_value(match.group("value")) for match in SECRET_ASSIGNMENT.finditer(value)):
            return True
        return any(
            not (_placeholder_value(match.group("user")) and _placeholder_value(match.group("password")))
            for match in CREDENTIAL_URL.finditer(value)
        )

    literal_nodes = [node for node in nodes if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes))]
    compile_literals = set()
    for node in literal_nodes:
        parent = parents.get(node)
        if not isinstance(parent, ast.Call) or not re_compile_call(parent):
            continue
        value = bytes_value(node.value)
        if value is None:
            continue
        # A recognizer is a compiled regex with named captures for arbitrary
        # path components, or multiple structural classes/groups. This does
        # not exempt concrete path literals passed to re.compile().
        named_arbitrary_capture = bool(re.search(rb"\(\?P<(?:user|host|share)>\[\^", value, re.I))
        structural_recognizer = (
            len(re.findall(rb"\[[^\]]+\]", value)) >= 2
            and b"(?:" in value
            and any(marker in value for marker in (b"*", b"+", b"?"))
        )
        if (named_arbitrary_capture or structural_recognizer) and not sensitive_literal(value):
            location = span(node)
            if location is not None:
                compile_literals.add((location[0], location[1]))

    def target_names(node):
        if isinstance(node, ast.Name):
            return {node.id}
        if isinstance(node, (ast.Tuple, ast.List)):
            names = set()
            for child in node.elts:
                names.update(target_names(child))
            return names
        return set()

    assignments = []
    for node in nodes:
        targets = []
        value = None
        if isinstance(node, ast.Assign):
            targets, value = node.targets, node.value
        elif isinstance(node, ast.AnnAssign):
            targets, value = [node.target], node.value
        elif isinstance(node, ast.NamedExpr):
            targets, value = [node.target], node.value
        names = set().union(*(target_names(target) for target in targets)) if targets else set()
        location = span(node)
        if not location or not names or value is None:
            continue
        kind = None
        if "pat" in names and re_compile_call(value):
            constants = [bytes_value(item.value) for item in ast.walk(value) if isinstance(item, ast.Constant) and isinstance(item.value, (str, bytes))]
            if all(item is not None and not sensitive_literal(item) for item in constants):
                kind = "CODE_REGEX_COMPILER"
        elif "token" in names and not isinstance(value, ast.Constant):
            constants = [bytes_value(item.value) for item in ast.walk(value) if isinstance(item, ast.Constant) and isinstance(item.value, (str, bytes))]
            if not constants:
                kind = "CODE_LOCAL_IDENTIFIER"
        if kind:
            assignments.append((location[0], location[1], names, kind))
    return {"payload": payload, "line_starts": line_starts, "literals": literal_nodes, "span": span,
            "compile_literals": compile_literals, "assignments": assignments, "sensitive_literal": sensitive_literal}


def _native_findings(records: dict, reviewed=None) -> set:
    findings = set()
    reviewed = reviewed if reviewed is not None else set()
    skipped_users = {b"user", b"username", b"name", b"account", b"yourname", b"<name>"}
    skipped_unc = {b"server", b"host", b"hostname", b"share", b"sharename", b"<server>", b"<share>"}
    for rel, record in records.items():
        path = record["file"]
        try:
            payload = path.read_bytes()
            lines = payload.splitlines(keepends=True)
            contexts = _python_code_context(record)
            offsets = 0
            for line_number, line in enumerate(lines, 1):
                line_start = offsets
                offsets += len(line)

                def add(category: str, match=None, *, key=None):
                    if contexts is not None and match is not None:
                        absolute_start = line_start + match.start()
                        absolute_end = line_start + match.end()
                        if category == "private_path":
                            for start, end in contexts["compile_literals"]:
                                if start <= absolute_start and absolute_end <= end:
                                    reviewed.add((rel, line_number, "DETECTOR_REGEX_LITERAL"))
                                    return
                            for literal in contexts["literals"]:
                                location = contexts["span"](literal)
                                if not location or not (location[0] <= absolute_start and absolute_end <= location[1]):
                                    continue
                                value = literal.value
                                decoded = value if isinstance(value, bytes) else value.encode("utf-8")
                                if not contexts["sensitive_literal"](decoded):
                                    reviewed.add((rel, line_number, "CODE_ESCAPED_LITERAL"))
                                    return
                        if category == "token_or_secret" and key in {b"token", b"pat"}:
                            for start, end, names, kind in contexts["assignments"]:
                                if start <= absolute_start and absolute_end <= end and key.decode("ascii") in names:
                                    reviewed.add((rel, line_number, kind))
                                    return
                    findings.add((rel, line_number, category))

                for match in PRIVATE_WINDOWS_HOME.finditer(line):
                    if match.group("user").lower() not in skipped_users:
                        add("private_path", match)
                for match in PRIVATE_WORKSPACE.finditer(line):
                    add("private_path", match)
                for match in PRIVATE_UNIX_HOME.finditer(line):
                    if match.group("user").lower() not in skipped_users:
                        add("private_path", match)
                for match in PRIVATE_UNC.finditer(line):
                    if match.group("host").lower() not in skipped_unc or match.group("share").lower() not in skipped_unc:
                        add("private_path", match)
                for match in PRIVATE_EMAIL.finditer(line):
                    if not match.group("domain").lower().endswith(b".invalid"):
                        add("private_email", match)
                for match in SECRET_ASSIGNMENT.finditer(line):
                    if _placeholder_value(match.group("value")):
                        continue
                    key = match.group("key").lower()
                    if b"password" in key or key in {b"passwd", b"pwd"}:
                        category = "password"
                    elif b"url" in key:
                        category = "credential_url"
                    else:
                        category = "token_or_secret"
                    add(category, match, key=key)
                for match in CREDENTIAL_URL.finditer(line):
                    if _placeholder_value(match.group("user")) and _placeholder_value(match.group("password")):
                        continue
                    add("credential_url", match)
        except OSError as exc:
            raise PublishScanError(f"candidate object could not be scanned: {rel}") from exc
    return findings


def _artifact_digest_locations(records: dict) -> set:
    """Identify only path-bound SHA-256 fields proven by candidate object bytes.

    This is deliberately structural: a field named ``<stem>_sha256`` is
    accepted as an artifact digest only when the same YAML object contains one
    ``<stem>_path`` scalar and that path resolves to an object in this exact
    candidate snapshot whose bytes hash to the recorded value. A bare
    64-character value is never enough.
    """
    locations = set()
    for rel, record in records.items():
        try:
            text = record["file"].read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        path_fields = {}
        digest_fields = {}
        for line_number, line in enumerate(text.splitlines(), 1):
            scalar = YAML_SCALAR_RE.match(line)
            if scalar:
                key = scalar.group("key")
                value = scalar.group("double")
                if value is None:
                    value = scalar.group("single")
                if value is None:
                    value = scalar.group("plain")
                if key.endswith("_path"):
                    path_fields.setdefault(key, []).append(value)
            digest = YAML_DIGEST_RE.match(line)
            if digest:
                value = digest.group("double") or digest.group("single") or digest.group("plain")
                digest_fields.setdefault(digest.group("key"), []).append((line_number, value.lower()))

        for digest_key, digest_rows in digest_fields.items():
            path_key = digest_key[:-len("_sha256")] + "_path"
            paths = path_fields.get(path_key, [])
            if len(digest_rows) != 1 or len(paths) != 1:
                continue
            try:
                target_rel = _safe_rel(paths[0])
            except PublishScanError:
                continue
            target = records.get(target_rel)
            if target is None:
                continue
            try:
                actual = hashlib.sha256(target["file"].read_bytes()).hexdigest()
            except OSError as exc:
                raise PublishScanError(f"candidate artifact digest target could not be read: {target_rel}") from exc
            if actual == digest_rows[0][1]:
                locations.add((rel, digest_rows[0][0]))
    return locations


def _gitleaks_class(rule_id: str, description: str) -> str:
    label = (rule_id + " " + description).lower()
    if "password" in label or "passwd" in label:
        return "password"
    if "url" in label or "uri" in label or "connection" in label:
        return "credential_url"
    if "email" in label or "user" in label:
        return "private_identity_or_credential"
    return "token_or_secret"


def _report_relative_path(raw: str, wrapper: str) -> str:
    if not isinstance(raw, str):
        raise PublishScanError("secret scanner returned an invalid object location")
    normalized = raw.replace("\\", "/")
    marker = wrapper + "/"
    at = normalized.rfind(marker)
    if at < 0:
        raise PublishScanError("secret scanner returned an unmapped object location")
    return _safe_rel(normalized[at + len(marker):])


def _gitleaks_findings(scan_root: Path, payload_root: Path, records: dict, work: Path, verified_digests: set) -> tuple:
    executable = shutil.which("gitleaks")
    if not executable:
        raise PublishScanError("Gitleaks is unavailable; candidate scan failed closed")
    wrapper = payload_root.name
    report = work / ("gitleaks-" + wrapper + ".json")
    ignore_dir = work / "empty-gitleaks-ignore"
    ignore_dir.mkdir(exist_ok=True)
    env = os.environ.copy()
    env.pop("GITLEAKS_CONFIG", None)
    env.pop("GITLEAKS_CONFIG_TOML", None)
    command = [
        executable,
        "dir",
        "--redact=100",
        "--report-format=json",
        "--report-path", str(report),
        "--gitleaks-ignore-path", str(ignore_dir),
        "--ignore-gitleaks-allow",
        "--max-target-megabytes=0",
        "--max-archive-depth=0",
        "--no-banner",
        "--no-color",
        "--log-level=fatal",
        str(scan_root),
    ]
    try:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, env=env)
    except OSError as exc:
        raise PublishScanError("Gitleaks could not start; candidate scan failed closed") from exc
    try:
        rows = json.loads(report.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise PublishScanError("Gitleaks did not produce a readable redacted report") from exc
    if not isinstance(rows, list) or result.returncode not in {0, 1}:
        raise PublishScanError("Gitleaks could not complete the candidate scan")
    findings = set()
    verified = set()
    for row in rows:
        if not isinstance(row, dict):
            raise PublishScanError("Gitleaks report has an invalid finding")
        rel = _report_relative_path(row.get("File"), wrapper)
        if rel not in records:
            raise PublishScanError("Gitleaks finding does not map to a candidate object")
        try:
            line_number = int(row.get("StartLine") or row.get("Line") or 1)
        except (TypeError, ValueError) as exc:
            raise PublishScanError("Gitleaks finding has an invalid line number") from exc
        if line_number < 1:
            raise PublishScanError("Gitleaks finding has an invalid line number")
        if (rel, line_number) in verified_digests:
            verified.add((rel, line_number, "VERIFIED_ARTIFACT_DIGEST"))
            continue
        category = _gitleaks_class(str(row.get("RuleID") or ""), str(row.get("Description") or ""))
        findings.add((rel, line_number, category))
    if result.returncode == 1 and not findings and not verified:
        raise PublishScanError("Gitleaks returned a finding status without a report entry")
    return findings, verified


def _empty_state_errors(records: dict) -> list:
    errors = []
    current = records.get("CURRENT.md")
    if current is None:
        return ["CURRENT.md: bootstrap state is missing"]
    try:
        current_text = current["file"].read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        errors.append("CURRENT.md: bootstrap state is unreadable")
        current_text = ""
    if "尚未开始项目执行轮次" not in current_text or not re.search(r"Latest TR[^\r\n]*不适用", current_text):
        errors.append("CURRENT.md: fresh candidate must retain its empty initial state")
    if SOURCE_RE.search(current_text) or "最新完整用户报告" in current_text or "USER REPORT" in current_text:
        errors.append("CURRENT.md: source execution history is not allowed in a fresh candidate")

    framework = records.get(".agent-project-control/framework.yaml")
    if framework is None:
        errors.append(".agent-project-control/framework.yaml: bootstrap framework file is missing")
    else:
        try:
            framework_text = framework["file"].read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            errors.append(".agent-project-control/framework.yaml: bootstrap framework file is unreadable")
        else:
            if not re.search(r"(?m)^template_source:\s*false\s*$", framework_text):
                errors.append(".agent-project-control/framework.yaml: fresh candidate must not claim template-source runtime state")

    for base, ids in OPERATIONAL_INDEXES.items():
        allowed = {base + "/.apcf-dir.yaml", base + "/INDEX.md"}
        for rel in records:
            if rel.startswith(base + "/") and rel not in allowed:
                errors.append(f"{rel}: source history or operational data is not allowed in a fresh candidate")
        index = records.get(base + "/INDEX.md")
        if index is None:
            errors.append(f"{base}/INDEX.md: empty bootstrap index is missing")
        else:
            try:
                index_text = index["file"].read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                errors.append(f"{base}/INDEX.md: bootstrap index is unreadable")
            else:
                pattern = re.compile(r"\b(?:" + ids + r")-\d{4,}\b")
                if pattern.search(index_text):
                    errors.append(f"{base}/INDEX.md: historical object reference is not allowed in a fresh candidate")

    for rel in records:
        if rel.startswith(".agent-project-control/runtime/") and rel not in RUNTIME_ALLOWED:
            errors.append(f"{rel}: runtime artifact is not allowed in a fresh candidate")
    return errors


def _candidate_errors(candidate_raw: str, manifest_raw: str, zip_raw: str) -> tuple:
    candidate_arg = Path(candidate_raw).expanduser()
    if candidate_arg.is_symlink() or not candidate_arg.is_dir():
        return (["candidate-repo: an existing direct Git directory is required"], set(), set())
    try:
        candidate = candidate_arg.resolve(strict=True)
        git_dir = candidate / ".git"
        if git_dir.is_symlink() or not git_dir.is_dir():
            return (["candidate-repo: a self-contained .git directory is required"], set(), set())
        source = ROOT.resolve(strict=True)
        top = Path(os.fsdecode(_git_bytes(candidate, "rev-parse", "--show-toplevel", candidate=True)).strip()).resolve()
        common_raw = os.fsdecode(_git_bytes(candidate, "rev-parse", "--git-common-dir", candidate=True)).strip()
        source_common_raw = os.fsdecode(_git_bytes(ROOT, "rev-parse", "--git-common-dir")).strip()
        candidate_common = Path(common_raw)
        source_common = Path(source_common_raw)
        if not candidate_common.is_absolute():
            candidate_common = candidate / candidate_common
        if not source_common.is_absolute():
            source_common = ROOT / source_common
        candidate_common = candidate_common.resolve()
        source_common = source_common.resolve()
    except (OSError, PublishScanError):
        return (["candidate-repo: independent local Git metadata is unreadable"], set(), set())
    if os.path.normcase(str(top)) != os.path.normcase(str(candidate)) or os.path.normcase(str(candidate)) == os.path.normcase(str(source)):
        return (["candidate-repo: path must resolve to an independent Git root"], set(), set())
    if os.path.normcase(str(candidate_common)) == os.path.normcase(str(source_common)):
        return (["candidate-repo: Git object database must be independent from the source repository"], set(), set())
    alternates = candidate_common / "objects" / "info" / "alternates"
    if alternates.exists():
        return (["candidate-repo: external Git object alternates are not allowed"], set(), set())

    manifest_arg = Path(manifest_raw).expanduser()
    zip_arg = Path(zip_raw).expanduser()
    if zip_arg.is_symlink():
        return (["candidate ZIP must not be a symbolic link"], set(), set())
    try:
        manifest_path = manifest_arg.resolve(strict=True)
        zip_path = zip_arg.resolve(strict=True)
    except OSError:
        return (["manifest or candidate ZIP is unreadable"], set(), set())
    if _is_within(zip_path, candidate):
        return (["candidate ZIP must remain outside the candidate Git repository"], set(), set())

    errors = []
    findings = set()
    verified_digests = set()
    try:
        expected = _manifest(manifest_arg, candidate)
        entries = _index_entries(candidate, candidate=True)
        changes = _name_status(candidate, candidate=True)
    except PublishScanError as exc:
        return (["candidate inventory: " + str(exc)], findings, verified_digests)

    staged_deleted_paths = {
        paths[0] for status, paths in changes if status.startswith("D") and paths
    }
    retained_deleted = sorted(staged_deleted_paths & set(expected))
    if retained_deleted:
        return ([f"candidate manifest retains staged deleted object: {rel}" for rel in retained_deleted], findings, verified_digests)
    try:
        with tempfile.TemporaryDirectory(prefix="publish-guard-", dir=FRAMEWORK_ROOT / "runtime" / "runs") as raw_work:
            work = Path(raw_work)
            marker = work / ".apcf-dir.yaml"
            marker.write_text(meta_line("private", comment=True) + "\nschema: 1\nvisibility: private\n", encoding="utf-8")
            stage_scan = work / "stage-scan"
            zip_scan = work / "zip-scan"
            stage_scan.mkdir()
            zip_scan.mkdir()
            stage_payload = Path(tempfile.mkdtemp(prefix="payload-", dir=stage_scan))
            zip_payload = Path(tempfile.mkdtemp(prefix="payload-", dir=zip_scan))
            stage_records = _materialize_index(candidate, entries, stage_payload, expected)
            errors.extend(_check_inventory("candidate Git index", stage_records, expected))

            def get_candidate_blob(rel: str) -> bytes:
                if rel not in entries:
                    raise KeyError(rel)
                return _blob(candidate, entries[rel]["oid"], candidate=True)

            for rel in sorted(entries):
                errors.extend(_metadata_errors(rel, entries, get_candidate_blob))
            errors.extend(_empty_state_errors(stage_records))

            try:
                zip_records = _zip_payload(zip_path, zip_payload, expected)
            except PublishScanError as exc:
                errors.append("candidate ZIP: " + str(exc))
                zip_records = {}
            errors.extend(_check_inventory("candidate ZIP", zip_records, expected))

            stage_code_reviews = set()
            zip_code_reviews = set()
            findings.update(_native_findings(stage_records, stage_code_reviews))
            findings.update(_native_findings(zip_records, zip_code_reviews))
            verified_digests.update(stage_code_reviews)
            verified_digests.update(zip_code_reviews)
            stage_digest_locations = _artifact_digest_locations(stage_records)
            zip_digest_locations = _artifact_digest_locations(zip_records)
            stage_findings, stage_verified = _gitleaks_findings(stage_scan, stage_payload, stage_records, work, stage_digest_locations)
            findings.update(stage_findings)
            verified_digests.update(stage_verified)
            if zip_records:
                zip_findings, zip_verified = _gitleaks_findings(zip_scan, zip_payload, zip_records, work, zip_digest_locations)
                findings.update(zip_findings)
                verified_digests.update(zip_verified)
    except PublishScanError as exc:
        errors.append("candidate scan: " + str(exc))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        errors.append("candidate scan could not read one or more staged or archived objects")
    return errors, findings, verified_digests


def main() -> None:
    parser = argparse.ArgumentParser(description="APCF source publication gate and exact candidate-object scanner")
    parser.add_argument("--turn-dir")
    parser.add_argument("--candidate-repo", help="independent local Git root containing the release candidate")
    parser.add_argument("--manifest", help="private path/size/SHA-256 inventory outside the candidate repository")
    parser.add_argument("--candidate-zip", help="release ZIP whose actual members must match the manifest")
    args = parser.parse_args()

    candidate_args = (args.candidate_repo, args.manifest, args.candidate_zip)
    if any(candidate_args) and not all(candidate_args):
        parser.error("--candidate-repo, --manifest, and --candidate-zip must be supplied together")

    tr = resolve_delivery_turn(args.turn_dir)
    code, _ = enforce_entrypoint(entrypoint="publish", turn_dir_raw=tr)
    if code:
        raise SystemExit(code)

    errors = _source_stage_errors()
    if args.candidate_repo:
        # This validates the root source's real CURRENT/Source TURN history while
        # leaving its intentionally dirty Git index untouched. Candidate files are
        # checked against their own independent Git index and distribution manifest.
        errors.extend("source-state: " + item for item in validate_state(False))
        candidate_errors, findings, verified_digests = _candidate_errors(args.candidate_repo, args.manifest, args.candidate_zip)
        errors.extend(candidate_errors)
        for rel, line, category in sorted(verified_digests):
            print(f"INFO: secret-review: {rel}:{line}: {category}")
        for rel, line, category in sorted(findings):
            errors.append(f"secret-review: {rel}:{line}: {category}")
    else:
        # Preserve normal source-repository publication semantics.
        errors.extend("state-integrity: " + item for item in validate_state(True))

    if errors:
        for error in errors:
            print("FAIL:", error)
        raise SystemExit(2)
    if args.candidate_repo:
        print("PASS: source Full Gate, source CURRENT/Source TURN, independent candidate index, ZIP manifest, metadata, and secret review")
    else:
        print("PASS: publication guard and durable CURRENT/Source TURN state")


if __name__ == "__main__":
    try:
        main()
    except (GateError, EnforcementError) as exc:
        print(f"FAIL: {exc}")
        raise SystemExit(exc.code)
