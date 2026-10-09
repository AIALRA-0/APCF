# APCF-META {"schema":1,"visibility":"public"}
import argparse
import re
from collections import Counter, defaultdict
from pathlib import Path

TEST_RE = re.compile(
    r"^- 【(?P<status>未执行|进行中|PASS|FAIL|BLOCKED|不适用)】"
    r"【(?P<id>TEST-[A-Za-z0-9_-]+)】"
    r"【对应 (?P<refs>CL-[A-Za-z0-9_-]+(?:[、,， ]+CL-[A-Za-z0-9_-]+)*)】"
    r"【(?P<object>[^】\n]+)】："
    r"在【(?P<context>[^】\n]+)】下，"
    r"执行【(?P<action>[^】\n]+)】，"
    r"必须观察到【(?P<expected>[^】\n]+)】；"
    r"实际观察到【(?P<actual>[^】\n]+)】，"
    r"证据为【(?P<evidence>[^】\n]+)】\s*$"
)

CHECKLIST_RE = re.compile(
    r"^- 【(?P<status>未开始|进行中|已完成|阻塞|不适用)】"
    r"【(?P<id>CL-[A-Za-z0-9_-]+)】"
    r"【(?P<object>[^】\n]+)】：(?P<body>.+)$"
)

TEST_FORMAT_MARKER = "<!-- APCF-TEST-FORMAT v2 -->"
TEST_V1_RE = TEST_RE  # Retained for explicit historical fixtures; consumers use parse_tests.
TEST_HEAD_RE = re.compile(
    r"^- 【(?P<status>未执行|进行中|PASS|FAIL|BLOCKED|不适用)】"
    r"【(?P<id>TEST-[A-Za-z0-9_-]+)】"
    r"【对应 (?P<refs>CL-[A-Za-z0-9_-]+(?:[、,， ]+CL-[A-Za-z0-9_-]+)*)】"
    r"【(?P<object>[^】\r\n]+)】：(?P<body>[^\r\n]+)$"
)
TEST_FIELDS = ("context", "action", "expected", "actual", "evidence")
TEST_LABELS = ("操作", "预期", "实际", "证据")
TEST_START = "版本／环境／前提："


def _split_unescaped(text, delimiter):
    start = 0
    while True:
        index = text.find(delimiter, start)
        if index < 0:
            return None
        previous = index - 1
        while previous >= 0 and text[previous] == "\\":
            previous -= 1
        if (index - 1 - previous) % 2 == 0:
            return text[:index], text[index + len(delimiter):]
        start = index + len(delimiter)


def _decode_field(raw):
    # Unescaped field labels cannot be hidden in a value or repeated out of order.
    if any(_split_unescaped(raw, "；" + label + "：") is not None for label in TEST_LABELS):
        raise ValueError("repeated or out-of-order TEST v2 field")
    result, index = [], 0
    while index < len(raw):
        char = raw[index]
        if char == "\\":
            if index + 1 >= len(raw) or raw[index + 1] not in ("\\", "；"):
                raise ValueError("illegal TEST v2 field escaping")
            result.append(raw[index + 1])
            index += 2
        else:
            result.append(char)
            index += 1
    value = "".join(result).strip()
    if not value:
        raise ValueError("empty TEST v2 field")
    return value


def _encode_field(value):
    value = str(value).strip()
    if not value or "\n" in value or "\r" in value:
        raise ValueError("TEST field must be a nonempty single line")
    return value.replace("\\", "\\\\").replace("；", "\\；")


def parse_test_line(line):
    match = TEST_HEAD_RE.fullmatch(line.strip())
    if not match:
        return None
    row = match.groupdict()
    body = row.pop("body")
    if body.startswith(TEST_START):
        remaining, values = body[len(TEST_START):], []
        try:
            for label in TEST_LABELS:
                split = _split_unescaped(remaining, "；" + label + "：")
                if split is None:
                    return None
                value, remaining = split
                values.append(_decode_field(value))
            values.append(_decode_field(remaining))
        except ValueError:
            return None
        row.update(zip(TEST_FIELDS, values))
        row["format_version"] = 2
    else:
        old = TEST_V1_RE.fullmatch(line.strip())
        if not old:
            return None
        row = old.groupdict()
        row["format_version"] = 1
    row["refs"] = _split_refs(row["refs"])
    return row


def serialize_v2(row):
    refs = _split_refs(row["refs"]) if isinstance(row["refs"], str) else row["refs"]
    if not refs or len(set(refs)) != len(refs) or any(not re.fullmatch(r"CL-[A-Za-z0-9_-]+", x) for x in refs):
        raise ValueError("invalid or duplicate referenced Checklist IDs")
    if row["status"] not in ("未执行", "进行中", "PASS", "FAIL", "BLOCKED", "不适用"):
        raise ValueError("invalid TEST status")
    if not re.fullmatch(r"TEST-[A-Za-z0-9_-]+", row["id"]):
        raise ValueError("invalid TEST ID")
    obj = str(row["object"]).strip()
    if not obj or any(x in obj for x in "】\r\n"):
        raise ValueError("invalid TEST object")
    values = [_encode_field(row[field]) for field in TEST_FIELDS]
    return (f'- 【{row["status"]}】【{row["id"]}】【对应 {"、".join(refs)}】【{obj}】：'
            f'{TEST_START}{values[0]}；操作：{values[1]}；预期：{values[2]}；实际：{values[3]}；证据：{values[4]}')


def _marker_errors(text):
    markers = [line.strip() for line in text.splitlines() if "APCF-TEST-FORMAT" in line]
    errors = []
    if any(line != TEST_FORMAT_MARKER for line in markers):
        errors.append("unknown or damaged TEST format marker")
    if markers.count(TEST_FORMAT_MARKER) > 1:
        errors.append("duplicate TEST format marker")
    if TEST_FORMAT_MARKER in markers:
        significant = [line.strip() for line in text.splitlines() if line.strip() and not line.strip().startswith("<!-- APCF-META ")]
        if len(significant) < 2 or not significant[0].startswith("# ") or significant[1] != TEST_FORMAT_MARKER:
            errors.append("TEST v2 marker must follow the document heading")
    return errors


def _body_lines(text):
    lines=[]
    heading_skipped=False
    for raw in text.splitlines():
        stripped=raw.strip()
        if not stripped or stripped.startswith("<!-- APCF-META ") or stripped == TEST_FORMAT_MARKER:
            continue
        if not heading_skipped and stripped.startswith("# "):
            heading_skipped=True
            continue
        lines.append(stripped)
    return lines


def _split_refs(raw):
    return [x for x in re.split(r"[、,， ]+", raw.strip()) if x]


def parse_tests(text):
    tests=[]
    for line in _body_lines(text):
        row=parse_test_line(line)
        if row is None:
            continue
        tests.append(row)
    return tests


def parse_checklist(text):
    items=[]
    for line in _body_lines(text):
        m=CHECKLIST_RE.match(line)
        if not m:
            continue
        items.append(m.groupdict())
    return items


def validate_text(text, checklist_text=None):
    errors=_marker_errors(text)
    raw_lines=_body_lines(text)
    tests=parse_tests(text)

    for line in raw_lines:
        row=parse_test_line(line)
        if row is None:
            errors.append(f"unrecognized TEST record; every current acceptance item must be exactly one line: {line[:180]}")
        elif TEST_FORMAT_MARKER in text and row["format_version"] != 2:
            errors.append(f"{row['id']}: v2-marked TEST cannot contain legacy v1 syntax")

    if not tests:
        errors.append("TEST.md must contain at least one current TEST-ID record")
        return errors

    seen=set()
    for row in tests:
        tid=row["id"]
        if tid in seen:
            errors.append(f"duplicate TEST-ID: {tid}")
        seen.add(tid)
        if len(set(row["refs"])) != len(row["refs"]):
            errors.append(f"{tid} duplicate referenced CL-ID")
        for field in ("object","context","action","expected","actual","evidence"):
            if not row[field].strip():
                errors.append(f"{tid} empty required field: {field}")

    if checklist_text is not None:
        for line in _body_lines(checklist_text):
            if not CHECKLIST_RE.match(line):
                errors.append(f"unrecognized Checklist record; every current requirement must have a CL-ID and object: {line[:180]}")
        checklist=parse_checklist(checklist_text)
        if not checklist:
            errors.append("CHECKLIST.md has no parseable CL-ID records")
            return errors
        cl_by_id={x["id"]:x for x in checklist}
        if len(cl_by_id)!=len(checklist):
            errors.append("duplicate CL-ID in CHECKLIST.md")

        mapped=defaultdict(list)
        for row in tests:
            for cid in row["refs"]:
                if cid not in cl_by_id:
                    errors.append(f"{row['id']} references missing Checklist item: {cid}")
                else:
                    mapped[cid].append(row)

        for cid,item in cl_by_id.items():
            rows=mapped.get(cid,[])
            if not rows:
                errors.append(f"Checklist item has no TEST coverage: {cid}")
                continue
            if item["status"]=="已完成":
                active=[r for r in rows if r["status"]!="不适用"]
                if not active:
                    errors.append(f"completed Checklist item has no applicable TEST: {cid}")
                elif any(r["status"]!="PASS" for r in active):
                    states=", ".join(f"{r['id']}={r['status']}" for r in active)
                    errors.append(f"completed Checklist item has non-PASS current TEST: {cid}: {states}")

    return errors


def validate_file(test_path, checklist_path=None):
    test_path=Path(test_path)
    if not test_path.is_file():
        return [f"TEST.md missing: {test_path}"]
    checklist_text=None
    if checklist_path is not None:
        checklist_path=Path(checklist_path)
        if not checklist_path.is_file():
            return [f"CHECKLIST.md missing: {checklist_path}"]
        checklist_text=checklist_path.read_text(encoding="utf-8")
    return validate_text(test_path.read_text(encoding="utf-8"), checklist_text)


def summary_text(text):
    rows=parse_tests(text)
    return {
        "test_ids":len(rows),
        "statuses":dict(Counter(x["status"] for x in rows)),
    }


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("test_file")
    ap.add_argument("--checklist")
    a=ap.parse_args()
    errors=validate_file(a.test_file, a.checklist)
    if errors:
        for e in errors:
            print("FAIL:",e)
        raise SystemExit(2)
    s=summary_text(Path(a.test_file).read_text(encoding="utf-8"))
    print(f"PASS: current-turn TEST form; {s['test_ids']} TEST-ID; statuses={s['statuses']}")

if __name__=="__main__":
    main()
