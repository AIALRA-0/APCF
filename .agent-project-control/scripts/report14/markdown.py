# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
import re
import sys
from .contract import normalize, MAX_BYTES

# Vendored pure Python dependencies: reproducible offline parsing, no pip at runtime.
_vendor = str(Path(__file__).parent / '_vendor')
if _vendor not in sys.path:
    sys.path.insert(0, _vendor)
from markdown_it import MarkdownIt
from markdown_it.tree import SyntaxTreeNode

@dataclass
class Section:
    number: int
    title: str
    line: int
    end: int
    body_line: int
    nodes: list = field(default_factory=list)

@dataclass
class Document:
    text: str
    lines: list[str]
    nodes: list
    sections: list[Section]

def inline(node) -> str:
    if node.type == 'inline':
        return node.content
    return ''.join(inline(c) for c in node.children or [])

def literal(node) -> str:
    if node.type in ('text', 'code_inline'):
        return node.content
    if node.type in ('softbreak', 'hardbreak'):
        return '\n'
    return ''.join(literal(c) for c in node.children or [])

def children(node, kind):
    return [n for n in node.children or [] if n.type == kind]

def parse(text: str) -> Document:
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_BYTES:
        raise ValueError('report input size/type invalid')
    text = normalize(text)
    root = SyntaxTreeNode(MarkdownIt('commonmark', {'html': True, 'maxNesting': 40}).enable('table').parse(text))
    lines = text.splitlines(keepends=True)
    nodes = root.children or []
    sections = []
    for node in nodes:
        if node.type == 'heading' and node.tag == 'h2':
            m = re.fullmatch(r'(\d+)\. (.+)', inline(node))
            n, title = (int(m[1]), m[2]) if m else (0, inline(node))
            if sections:
                sections[-1].end = node.map[0]
            sections.append(Section(n, title, node.map[0], len(lines), node.map[1]))
        elif sections:
            sections[-1].nodes.append(node)
    return Document(text, lines, nodes, sections)

def body(doc: Document, section: Section) -> str:
    return ''.join(doc.lines[section.body_line:section.end]).strip('\n')

def body_model(text: str) -> dict:
    doc = parse(text)
    return {'contract_id': 'apcf-report14/1.0.0',
            'sections': [{'number': s.number, 'body': body(doc, s)} for s in doc.sections]}

def fields(nodes: list) -> list[dict]:
    result = []
    for node in nodes:
        if node.type != 'bullet_list':
            continue
        for item in node.children:
            paragraphs = children(item, 'paragraph')
            first = inline(paragraphs[0]) if paragraphs else ''
            match = re.match(r'^([^：\n]+)：([\s\S]*)$', first)
            label, value = (match[1], match[2]) if match else ('', first)
            if len(paragraphs) > 1:
                value += '\n\n' + '\n\n'.join(inline(p) for p in paragraphs[1:])
            result.append({'name': label, 'value': value, 'line': item.map[0],
                           'end': item.map[1], 'node': item,
                           'lists': [x for x in item.children if x.type in ('bullet_list','ordered_list')]})
    return result

def records(section: Section) -> tuple[list[dict], list]:
    out, orphan = [], []
    for node in section.nodes:
        value = inline(node)
        if node.type == 'paragraph' and value.startswith('**【'):
            match = re.fullmatch(r'\*\*((?:【[^】\n]+】){2,3})：\*\*', value)
            parts = re.findall(r'【([^】]+)】', match[1]) if match else []
            if out:
                out[-1]['end'] = node.map[0]
            out.append({'parts':parts,'title_node':node,'line':node.map[0],
                        'end':section.end,'nodes':[]})
        elif out:
            out[-1]['nodes'].append(node)
        else:
            orphan.append(node)
    for item in out:
        item['fields'] = fields(item['nodes'])
    return out, orphan
