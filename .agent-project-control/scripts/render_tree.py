# APCF-META {"schema":1,"visibility":"public"}
from html import escape
from common import ROOT,FRAMEWORK_ROOT,write_md,parse_meta
def main():
    items=[]
    for p in sorted(ROOT.rglob('*')):
        if p.is_dir() or '.git' in p.parts or '__pycache__' in p.parts: continue
        rel=p.relative_to(ROOT).as_posix()
        if rel.startswith('.codex/skills/') and rel!='.codex/skills/.apcf-dir.yaml': continue
        if rel.startswith('.agent-project-control/runtime/'):
            allowed={'.agent-project-control/runtime/.apcf-dir.yaml'}|{f'.agent-project-control/runtime/{x}/.apcf-dir.yaml' for x in ['testbed','runs','downloads','tmp','cache','large','distribution']}
            if rel not in allowed: continue
        metadata=parse_meta(p) or parse_meta(p.with_name(p.name+'.apcf-meta.yaml'))
        if metadata and metadata.get('visibility')=='private': continue
        if any((parse_meta(parent/'.apcf-dir.yaml') or {}).get('visibility')=='private' for parent in p.parents if parent!=ROOT and parent.is_relative_to(ROOT)): continue
        items.append(rel)
    write_md(FRAMEWORK_ROOT/'generated/TREE.md','# 1. 当前模板文件树\n\n本视图由脚本从真实文件系统生成，不手工维护\n\n```text\n'+'\n'.join(items)+'\n```')
    lis=''.join('<li><code>'+escape(x)+'</code></li>' for x in items); (FRAMEWORK_ROOT/'generated/TREE.html').write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n<!doctype html><meta charset="utf-8"><title>FRAMEWORK_ROOT Tree</title><h1>Agent Project Control Framework Tree</h1><ul>'+lis+'</ul>',encoding='utf-8'); print('PASS: tree rendered')
if __name__=='__main__': main()
