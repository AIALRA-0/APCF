# APCF-META {"schema":1,"visibility":"public"}
from common import ROOT,FRAMEWORK_ROOT,write_md
from rule_sync import sync as sync_rules
def render(title,root,prefix):
    items=[p for p in sorted(root.glob(prefix+'-*'))]
    lines=[f'# 1. {title}','','| ID / 名称 | 路径 |','|---|---|']
    if not items: lines.append('| 无 | 无 |')
    for p in items: lines.append(f'| `{p.name}` | `{p.relative_to(ROOT).as_posix()}` |')
    write_md(root/'INDEX.md','\n'.join(lines))
def main():
    sync_rules(True)
    for title,folder,prefix in [('IT 迭代索引','iterations','IT'),('REG 回归问题索引','regressions','REG'),('ADR 架构决策索引','decisions','ADR'),('RB 运行手册索引','runbooks','RB'),('MAT 材料索引','materials','MAT')]: render(title,FRAMEWORK_ROOT/folder,prefix)
    print('PASS: indexes refreshed')
if __name__=='__main__': main()
