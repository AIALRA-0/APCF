# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import re,unicodedata
from .contract import term_issues,Issue,TERMS

def scan_glossary_markdown(markdown:str,registry=None):
    """Legacy/current raw glossary audit. Does not globally edit prose or code."""
    out=[];inside=False;fence=None
    for line_no,line in enumerate(markdown.replace('\r\n','\n').splitlines(),1):
        f=re.match(r'^\s*(`{3,}|~{3,})',line)
        if f:
            if fence is None:fence=f.group(1)[0]
            elif fence==f.group(1)[0]:fence=None
            continue
        if fence:continue
        if re.match(r'^##\s+\d+\.\s',line):inside=bool(re.match(r'^##\s+3\.\s+术语表\s*$',line));continue
        if not inside or not line.strip():continue
        if not line.startswith('- '):
            out.append(Issue('TERM_LIST_LEVEL',f'/line/{line_no}','术语必须使用一级列表'));continue
        text=unicodedata.normalize('NFKC',line[2:]).replace('`','').replace('**','')
        m=re.match(r'(?:(?P<a>[A-Z][A-Z0-9_.-]{1,15})\s+)?(?P<zh>[^():]+)\((?P<en>[^()]+)\)[:：](?P<body>.*)',text)
        if not m:out.append(Issue('TERM_FORMAT',f'/line/{line_no}','需要准确的中文名称及英文名称'));continue
        term={'abbreviation':m.group('a') or '', 'chinese':m.group('zh').strip(),'english':m.group('en').strip(),'kind':'abbreviation' if m.group('a') else 'term'}
        out.extend(term_issues(term,registry or TERMS,f'/line/{line_no}'))
    return out
