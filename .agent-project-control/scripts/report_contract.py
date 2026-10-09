# APCF-META {"schema":1,"visibility":"public"}
import re
from pathlib import Path
from test_ledger import TEST_FORMAT_MARKER, validate_text as validate_test_ledger_text

SECTION_TITLES = [
    "精确状态头","承上启下","术语表","执行清单","验收记录",
    "完整讲解","关键要点","用户需要执行","需要继续讨论、搜索或决策","下一步推荐",
]
GENERIC_BP_TITLES = {
    "精准应用","完整账本","保留失败","统一状态","明确限制",
    "结果","总结","要点","状态","验证","改动","下一步","完成情况",
}
TOP_RE = re.compile(r"^#{1,4}\s+([0-9])\.(?![0-9])\s*(.+?)\s*$", re.M)
SUB_RE = re.compile(r"^#{2,6}\s+([0-9])\.([0-9]+)\.\s+(.+?)\s*$", re.M)
PLAIN_NESTED_RE = re.compile(r"^\s*([5-9])\.([0-9]+)\.\s+\S", re.M)
BP_RE = re.compile(r"^- \*\*(.+?)\*\*：(.+)$")
ARROW_TOKENS = ("→", "->", "=>", "⇒", "⟶")


def split_sections(report):
    matches = list(TOP_RE.finditer(report))
    sections, order = {}, []
    for i, m in enumerate(matches):
        n = int(m.group(1))
        end = matches[i + 1].start() if i + 1 < len(matches) else len(report)
        sections[n] = (m.group(2).strip(), report[m.end():end].strip())
        order.append(n)
    return order, sections


def meaningful_file_lines(path):
    text = Path(path).read_text(encoding="utf-8")
    out, skipped_heading = [], False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("<!-- APCF-META ") or line == TEST_FORMAT_MARKER:
            continue
        if not skipped_heading and line.startswith("# "):
            skipped_heading = True
            continue
        out.append(line)
    return out


def require_embedded(source_path, body, label):
    errors = []
    for line in meaningful_file_lines(source_path):
        if line not in body:
            errors.append(f"{label} missing current source line: {line[:180]}")
    return errors


def split_paragraphs(body):
    return [p.strip() for p in re.split(r"\n\s*\n", body.strip()) if p.strip()]


def validate_handoff(body):
    errors=[]
    paragraphs=split_paragraphs(body)
    if not (2 <= len(paragraphs) <= 4):
        errors.append(f"section 1 must use 2-4 short prose paragraphs; found {len(paragraphs)}")
    for i,p in enumerate(paragraphs,1):
        lines=[x.strip() for x in p.splitlines() if x.strip()]
        if any(x.startswith("- ") for x in lines):
            errors.append(f"section 1 paragraph {i} must be prose, not a bullet list")
        if any(token in p for token in ARROW_TOKENS):
            errors.append(f"section 1 paragraph {i} must express the logic chain with natural language, not arrows")
    return errors


def bp_items(body, label):
    errors, count = [], 0
    for raw in body.splitlines():
        line = raw.strip()
        if not line.startswith("- "):
            continue
        m = BP_RE.match(line)
        if not m:
            errors.append(f"{label} bullet missing descriptive bold title + Chinese colon: {line[:180]}")
            continue
        count += 1
        title = m.group(1).strip()
        content = m.group(2).strip()
        if title in GENERIC_BP_TITLES:
            errors.append(f"{label} uses generic title instead of proposition-like main idea: {title}")
        if any(token in content for token in ARROW_TOKENS):
            errors.append(f"{label} BP body must use complete natural-language sentences instead of arrow-linked fragments: {title}")
    if count == 0:
        errors.append(f"{label} requires at least one titled BP")
    return errors


def validate_hierarchy(report):
    errors = []
    for m in PLAIN_NESTED_RE.finditer(report):
        line = report[m.start():].splitlines()[0]
        if not line.lstrip().startswith("#"):
            errors.append(f"nested number {m.group(1)}.{m.group(2)} must be a real subheading, not a flat list item")
    _, sections = split_sections(report)
    for n, (_, body) in sections.items():
        subs = [(int(a), int(b), t) for a, b, t in SUB_RE.findall(body)]
        expected = 1
        for parent, child, _ in subs:
            if parent != n:
                errors.append(f"subheading {parent}.{child} appears inside section {n}")
            if child != expected:
                errors.append(f"section {n} subheading sequence expected {n}.{expected}, found {parent}.{child}")
            expected = child + 1
    return errors


def validate_report(report, turn_dir):
    errors = []
    order, sections = split_sections(report)
    if order != list(range(10)):
        return [f"top-level report sections must be exactly 0..9 in order; found {order}"]
    for n, title in enumerate(SECTION_TITLES):
        if sections[n][0] != title:
            errors.append(f"section {n} title must be '{title}', found '{sections[n][0]}'")

    status = sections[0][1]
    if not any(x.strip().startswith("- ") for x in status.splitlines()):
        errors.append("section 0 must use a bullet status list")
    for token in ("IT", "TR"):
        if token not in status:
            errors.append(f"section 0 missing {token}")
    if "Checklist" not in status and "执行清单" not in status:
        errors.append("section 0 missing Checklist summary")
    if "Test" not in status and "验收" not in status:
        errors.append("section 0 missing Test summary")
    if re.search(r"\bAttempt\b|历史失败\s*\d+\s*次|尝试\s*\d+\s*次", status, re.I):
        errors.append("section 0 must summarize current TEST-ID statuses only, not attempt history")

    errors += validate_handoff(sections[1][1])

    terms = [x for x in sections[2][1].splitlines() if x.strip()]
    if terms and not all(x.strip().startswith("- ") for x in terms):
        errors.append("section 2 must be a term bullet list")

    tr = Path(turn_dir)
    errors += require_embedded(tr / "CHECKLIST.md", sections[3][1], "section 3")
    errors += require_embedded(tr / "TEST.md", sections[4][1], "section 4")
    source_test = (tr / "TEST.md").read_text(encoding="utf-8")
    errors += ["current TEST source: " + e for e in validate_test_ledger_text(
        source_test, (tr / "CHECKLIST.md").read_text(encoding="utf-8")
    )]
    reported_lines = [line.strip() for line in sections[4][1].splitlines()
                      if line.strip() and line.strip() != TEST_FORMAT_MARKER]
    if reported_lines != meaningful_file_lines(tr / "TEST.md"):
        errors.append("section 4 must contain exactly the current TEST lines in source order")
    # The invisible schema line may be omitted from the report, but its contract
    # still applies to the report's visible acceptance records.
    embedded_test = sections[4][1]
    if TEST_FORMAT_MARKER in source_test:
        visible = "\n".join(line for line in embedded_test.splitlines()
                            if line.strip() != TEST_FORMAT_MARKER)
        embedded_test = "# 1. 当前验收记录\n\n" + TEST_FORMAT_MARKER + "\n\n" + visible
    errors += [
        "section 4 TEST form: "+e
        for e in validate_test_ledger_text(embedded_test, sections[3][1])
    ]

    if not sections[5][1].strip():
        errors.append("section 5 full explanation is empty")
    errors += bp_items(sections[6][1], "section 6")

    for n in (7, 8):
        body = sections[n][1]
        if not body.strip():
            errors.append(f"section {n} is empty")
        if not SUB_RE.search(body):
            lines = [x.strip() for x in body.splitlines() if x.strip()]
            if lines and not any(x.startswith("- ") for x in lines):
                errors.append(f"section {n} flat content must use bullets; do not invent {n}.1 numbering")

    errors += bp_items(sections[9][1], "section 9")
    errors += validate_hierarchy(report)
    return errors
