# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from report_bridge.contract import ContractError, canonical, digest
from report_bridge.storage import atomic, verify_envelope


_HEX = re.compile(r"^[a-f0-9]{64}$")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ContractError("OBSERVER_REDIRECT_NOT_ALLOWED")


def _source_snapshot(report: dict) -> dict:
    """Rebuild the source object used by native.capture and bind it to its digest."""
    facts = report.get("facts")
    manifest = facts.get("native-manifest") if isinstance(facts, dict) else None
    if not isinstance(report.get("native_sources"), dict) or not isinstance(manifest, dict):
        raise ContractError("SOURCE_SNAPSHOT_UNAVAILABLE")
    source = {
        "identity": report.get("identity"),
        "sources": report["native_sources"],
        "facts": facts,
        "manifest": manifest.get("value"),
    }
    if not isinstance(source["manifest"], list) or digest(source) != report.get("source_digest"):
        raise ContractError("SOURCE_DIGEST_MISMATCH")
    return source


def _binding(path: Path, identity: dict) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ContractError("OBSERVER_BINDING_UNAVAILABLE") from None
    if not isinstance(value, dict):
        raise ContractError("OBSERVER_BINDING_INVALID")
    for field in ("ownerId", "projectId", "producerId", "externalProjectId"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise ContractError("OBSERVER_BINDING_INVALID")
    if value.get("mode") != "observe" or value.get("enabled") is not True:
        raise ContractError("OBSERVER_BINDING_DISABLED")
    if value["producerId"] != identity["producer_id"] or value["externalProjectId"] != identity["project_id"]:
        raise ContractError("OBSERVER_PRODUCER_BINDING")
    if any(c in value["ownerId"] for c in "\r\n"):
        raise ContractError("OBSERVER_BINDING_INVALID")
    iterations = value.get("iterationMappings")
    turns = value.get("turnMappings")
    iteration = identity["iteration_id"]
    turn = identity["turn_id"]
    if not isinstance(iterations, dict) or iteration not in iterations or not isinstance(turns, dict):
        raise ContractError("OBSERVER_TURN_UNMAPPED")
    mapped = next((row for key, row in turns.items()
                   if isinstance(row, dict)
                   and row.get("externalIterationId") == iteration
                   and row.get("externalTurnId", key) == turn), None)
    if mapped is None:
        raise ContractError("OBSERVER_TURN_UNMAPPED")
    return value


def _endpoint(value: str, project_id: str, producer_id: str):
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        raise ContractError("UNSAFE_ENDPOINT") from None
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (parsed.scheme != "https" and not (parsed.scheme == "http" and local)):
        raise ContractError("HTTPS_REQUIRED")
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or any(c in value for c in "\r\n")):
        raise ContractError("UNSAFE_ENDPOINT")
    expected_path = "/machine/v1/report-observations/projects/" + urllib.parse.quote(project_id, safe="")
    expected_path += "/" + urllib.parse.quote(producer_id, safe="")
    if parsed.path != expected_path:
        raise ContractError("OBSERVER_ROUTE_BINDING")
    return parsed, (parsed.scheme, parsed.hostname.lower(), port)


def _native_object_digest(value: dict, module_path: str | None = None) -> str:
    configured_module = module_path or os.environ.get("AEMP_NATIVE_CONTRACTS_MODULE")
    if not configured_module:
        raise ContractError("NATIVE_REQUEST_DIGEST_UNAVAILABLE")
    module = Path(configured_module)
    try:
        module_uri = module.resolve(strict=True).as_uri()
        code = (
            "import {digestObject} from " + json.dumps(module_uri) + ";"
            "process.stdin.setEncoding('utf8');let s='';"
            "for await(const c of process.stdin)s+=c;"
            "process.stdout.write(digestObject(JSON.parse(s)));"
        )
        result = subprocess.run(
            ["node", "--input-type=module", "-e", code],
            input=canonical(value), capture_output=True, timeout=15, check=False,
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ContractError("NATIVE_REQUEST_DIGEST_UNAVAILABLE") from None
    if result.returncode or not _HEX.fullmatch(result.stdout.decode("ascii", errors="ignore")):
        raise ContractError("NATIVE_REQUEST_DIGEST_UNAVAILABLE")
    return result.stdout.decode("ascii")


def _ack(ack: dict, envelope: dict, binding: dict, base_url: str) -> dict:
    expected = {
        "schema": "apcf.observation-ack/1",
        "projectId": binding["projectId"],
        "identity": envelope["identity"],
        "revision": envelope["revision"],
        "reportDigest": envelope["report_digest"],
        "envelopeDigest": envelope["envelope_digest"],
        "authority": "observation_only",
    }
    if not isinstance(ack, dict) or any(ack.get(key) != value for key, value in expected.items()):
        raise ContractError("ACK_BINDING_MISMATCH")
    if ack.get("status") not in ("stored", "already_stored"):
        raise ContractError("ACK_SCOPE")
    locator = ack.get("locator")
    if not isinstance(locator, str) or not locator.strip():
        raise ContractError("ACK_LOCATOR_MISSING")
    target = urllib.parse.urlsplit(urllib.parse.urljoin(base_url, locator))
    base = urllib.parse.urlsplit(base_url)
    if (target.scheme, target.hostname, target.port) != (base.scheme, base.hostname, base.port):
        raise ContractError("ACK_CROSS_ORIGIN")
    # AEMP returns a root-relative reader URL. Publish only the same-origin,
    # absolute URL that was actually checked, so desktop Markdown can open it.
    return {**ack, "locator": urllib.parse.urlunsplit(target)}


def _request(opener, method: str, url: str, *, token: str, owner_id: str, timeout: int,
             envelope: dict | None = None, native_digest: str | None = None):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "x-aemp-observation-owner": owner_id,
    }
    body = None
    if envelope is not None:
        headers.update({
            "Content-Type": "application/json",
            "Idempotency-Key": envelope["envelope_digest"],
            "x-aemp-object-digest": native_digest or "",
        })
        body = canonical(envelope)
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with opener.open(request, timeout=timeout) as response:
            status = response.status
            raw = response.read(1_000_001)
    except urllib.error.HTTPError as error:
        status = error.code
        raw = error.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ContractError("ACK_TOO_LARGE")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ContractError("ACK_INVALID_JSON") from None
    if not isinstance(value, dict):
        raise ContractError("ACK_INVALID_JSON")
    return status, value


def _persist_ack(file: Path, ack: dict):
    target = file.with_suffix(".ack.json")
    data = canonical(ack)
    if target.exists():
        try:
            existing = json.loads(target.read_bytes().decode("utf-8-sig"))
            before, after = dict(existing), dict(ack)
            if (before.get("status") not in ("stored", "already_stored")
                    or after.get("status") not in ("stored", "already_stored")
                    or not isinstance(before.get("locator"), str)):
                raise ValueError("invalid existing acknowledgement")
            before["locator"] = urllib.parse.urljoin(after["locator"], before["locator"])
            before.pop("status"); after.pop("status")
        except (ValueError, TypeError, KeyError):
            raise ContractError("ACK_COLLISION") from None
        # Replay status describes this request, not a changed report. Every
        # identity, digest, artifact and reader location must still be equal.
        # Preserve the first stored acknowledgement as immutable evidence.
        if canonical(before) != canonical(after):
            raise ContractError("ACK_COLLISION")
        return
    atomic(target, data)


def send_once(file: Path, endpoint: str, token_env: str, *, enabled=False, timeout=10,
              query_endpoint: str | None = None, binding_file: str | Path | None = None,
              native_contracts_module: str | None = None) -> dict:
    """Query and, only after definitive absence, submit one immutable outbox envelope.

    The legacy positional API is unchanged. Binding and credentials stay outside the
    repository; the default remains disabled and this function never creates a grant.
    """
    if enabled is not True:
        return {"status": "disabled", "sent": False}
    path = Path(file)
    try:
        raw = path.read_bytes()
        envelope = json.loads(raw.decode("utf-8-sig"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ContractError("OUTBOX_UNAVAILABLE") from None
    report = verify_envelope(envelope)
    _source_snapshot(report)
    if path.parent.name == "outbox" and path.stem != envelope.get("envelope_digest"):
        raise ContractError("OUTBOX_KEY_MISMATCH")
    if path.parent.name == "outbox" and raw != canonical(envelope):
        raise ContractError("OUTBOX_NOT_CANONICAL")

    configured_binding = binding_file or os.environ.get("APCF_OBSERVER_BINDING_FILE")
    if not configured_binding:
        raise ContractError("OBSERVER_BINDING_UNAVAILABLE")
    binding = _binding(Path(configured_binding), envelope["identity"])
    post, post_origin = _endpoint(endpoint, binding["projectId"], envelope["identity"]["producer_id"])
    query_url = query_endpoint or endpoint
    query, query_origin = _endpoint(query_url, binding["projectId"], envelope["identity"]["producer_id"])
    if post_origin != query_origin:
        raise ContractError("OBSERVER_CROSS_ORIGIN")

    token = os.environ.get(token_env)
    if (not isinstance(token, str) or not token.startswith("aemp-report.")
            or len(token) == len("aemp-report.") or any(c.isspace() for c in token)):
        raise ContractError("OBSERVER_CREDENTIAL_UNAVAILABLE")

    opener = urllib.request.build_opener(NoRedirect())
    bounded_timeout = min(max(int(timeout), 1), 20)
    query_args = urllib.parse.urlencode({
        "iteration_id": envelope["identity"]["iteration_id"],
        "turn_id": envelope["identity"]["turn_id"],
        "revision": envelope["revision"],
        "report_digest": envelope["report_digest"],
        "envelope_digest": envelope["envelope_digest"],
    })
    try:
        status, result = _request(
            opener, "GET", query_url + "?" + query_args, token=token,
            owner_id=binding["ownerId"], timeout=bounded_timeout,
        )
    except Exception:
        raise ContractError("OBSERVATION_QUERY_UNCONFIRMED_NO_POST") from None
    if status == 200:
        ack = _ack(result, envelope, binding, query_url)
        _persist_ack(path, ack)
        return ack
    if status != 404 or result.get("error") != "observation_not_found":
        raise ContractError("OBSERVATION_QUERY_NOT_DEFINITIVE_NO_POST")

    if path.read_bytes() != raw:
        raise ContractError("OUTBOX_CHANGED_BEFORE_POST")
    request_digest = _native_object_digest(envelope, native_contracts_module)
    try:
        status, result = _request(
            opener, "POST", endpoint, token=token, owner_id=binding["ownerId"],
            timeout=bounded_timeout, envelope=envelope, native_digest=request_digest,
        )
    except Exception:
        raise ContractError("OBSERVATION_POST_UNCONFIRMED_QUERY_REQUIRED") from None
    if status not in (200, 201):
        raise ContractError("OBSERVATION_POST_UNCONFIRMED_QUERY_REQUIRED")
    ack = _ack(result, envelope, binding, endpoint)
    if path.read_bytes() != raw:
        raise ContractError("OUTBOX_CHANGED_AFTER_POST")
    _persist_ack(path, ack)
    return ack
