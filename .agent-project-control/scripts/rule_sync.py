# APCF-META {"schema":1,"visibility":"public"}
from pathlib import Path
import re
from common import ROOT
MODULES=[
    '.agent-project-control/rules/01-context-state.md',
    '.agent-project-control/rules/02-execution-scope.md',
    '.agent-project-control/rules/03-verification-regression.md',
    '.agent-project-control/rules/04-tools-parallel.md',
    '.agent-project-control/rules/05-delivery-lifecycle.md',
    '.agent-project-control/rules/06-framework-contract.md',
]
RULE_HEADING=re.compile(r'^##[ \t]+\d+\.\d+\.[ \t]+(R\d+)\b(?:[ \t]+(.*))?$',re.M)
def canonical_rules():
    rows=[]
    for rel in MODULES:
        p=ROOT/rel
        if not p.exists(): raise ValueError(f'canonical module missing: {rel}')
        text=p.read_text(encoding='utf-8')
        for m in RULE_HEADING.finditer(text):
            rows.append((m.group(1),(m.group(2) or '').strip(),Path(rel).name))
    rows.sort(key=lambda x:int(x[0][1:]))
    return rows

def validate_rule_ids(rows):
    expected={f'R{i:02d}' for i in range(1,32)}
    owners={}
    for rid,_,module in rows: owners.setdefault(rid,[]).append(module)
    errors=[]
    missing=sorted(expected-set(owners))
    if missing: errors.append('missing Rule IDs: '+', '.join(missing))
    for rid,modules in sorted(owners.items()):
        if rid not in expected: errors.append(f'unknown Rule ID {rid}: '+', '.join(modules))
        if len(modules)!=1: errors.append(f'duplicate Rule ID {rid}: '+', '.join(modules))
    if errors: raise ValueError('; '.join(errors))
def render_index(rows):
    lines=['<!-- APCF-META {"schema":1,"visibility":"public"} -->','# 1. 规则索引','',
        '本文件只负责把规则标识（Rule ID）路由到唯一规范模块；规则标题与完整正文以对应规范模块为唯一权威，本索引不得复制规则摘要','',
        '| 规则标识（Rule ID） | 唯一规范模块 |','|---|---|']
    for rid,title,module in rows: lines.append(f'| `{rid}` | `{module}` |')
    lines += ['','## 1.1. 完整性要求','',
        '- `R01` 至 `R31` 必须连续且唯一',
        '- 每个规则标识只能映射到一个规范模块正文',
        '- `AGENTS.md` 首部关键规则索引和最终回读索引属于规范模块标题的派生表面；不得独立改写规则摘要',
        '- 规范模块缺失、重复、索引不一致或派生表面漂移时，确定性检查必须失败','']
    return '\n'.join(lines)
def render_rule_block(rows):
    modules={Path(rel).name:[] for rel in MODULES}
    for rid,_,module in rows: modules[module].append(rid)
    return '\n'.join(f'- `{module}` → `{", ".join(sorted(ids,key=lambda rid:int(rid[1:])))}`' for module,ids in modules.items())
def replace_marked(text,start,end,body):
    if text.count(start)!=1 or text.count(end)!=1:
        raise ValueError(f'marker must occur exactly once: {start} / {end}')
    pat=re.compile(re.escape(start)+r'.*?'+re.escape(end),re.S)
    repl=start+'\n'+body+'\n'+end
    if not pat.search(text): raise ValueError(f'marker missing: {start}')
    return pat.sub(repl,text,count=1)
def sync(write=True):
    rows=canonical_rules()
    validate_rule_ids(rows)
    idx=render_index(rows)
    agp=ROOT/'AGENTS.md'; ag=agp.read_text(encoding='utf-8')
    block=render_rule_block(rows)
    ag2=replace_marked(ag,'<!-- APCF-RULE-INDEX-START -->','<!-- APCF-RULE-INDEX-END -->',block)
    ag2=replace_marked(ag2,'<!-- APCF-RULE-READBACK-START -->','<!-- APCF-RULE-READBACK-END -->',block)
    if write:
        index_path=ROOT/'.agent-project-control/rules/INDEX.md'
        if not index_path.exists() or index_path.read_text(encoding='utf-8')!=idx+'\n':
            index_path.write_text(idx+'\n',encoding='utf-8')
        if ag!=ag2: agp.write_text(ag2,encoding='utf-8')
    return rows,idx+'\n',ag2
if __name__=='__main__':
    sync(True)
    print('PASS: rule surfaces synchronized')
