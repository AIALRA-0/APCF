# APCF-META {"schema":1,"visibility":"public"}
"""Generate searchable, expandable source tree without traversing dependency sandboxes."""
from html import escape
import os
from pathlib import Path
from common import ROOT,FRAMEWORK_ROOT,write_md,parse_meta
from repair_io import linked

def inventory():
    items=[]
    for folder,dirs,files in os.walk(ROOT,followlinks=False):
        parent=Path(folder)
        if parent!=ROOT and (parse_meta(parent/'.apcf-dir.yaml') or {}).get('visibility')=='private':dirs[:]=[];continue
        dirs[:]=sorted(d for d in dirs if d not in {'.git','__pycache__','node_modules','.venv'} and not linked(parent/d))
        for name in sorted(files):
            p=parent/name;rel=p.relative_to(ROOT).as_posix()
            if linked(p) or rel.startswith('.codex/skills/') and name!='.apcf-dir.yaml':continue
            meta=parse_meta(p) or parse_meta(p.with_name(name+'.apcf-meta.yaml'))
            if meta and meta.get('visibility')=='private':continue
            items.append(rel)
    return sorted(items)

def tree_html(items):
    tree={}
    for rel in items:
        node=tree
        for part in rel.split('/'):node=node.setdefault(part,{})
    def render(node):
        rows=[]
        for name,children in sorted(node.items()):
            label=escape(name)
            if children:rows.append(f'<li><details open><summary>{label}/</summary><ul>{render(children)}</ul></details></li>')
            else:rows.append(f'<li class="file"><code>{label}</code></li>')
        return ''.join(rows)
    return render(tree)

def main():
    items=inventory()
    write_md(FRAMEWORK_ROOT/'generated/TREE.md','# 1. 当前模板文件树\n\n本视图由实际公开文件生成；不遍历私有运行区，不手工维护\n\n```text\n'+'\n'.join(items)+'\n```')
    page='''<!-- APCF-META {"schema":1,"visibility":"public"} -->
<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>APCF 文件结构</title>
<style>body{max-width:1000px;margin:32px auto;padding:0 20px;font:15px/1.7 system-ui;background:#f8f8f6;color:#222}ul{list-style:none;padding-left:22px}summary{cursor:pointer}input,button{font:inherit;padding:8px 12px;margin:6px;border:1px solid #aaa;border-radius:6px}.file{padding:2px 0}code{overflow-wrap:anywhere}</style>
<h1>APCF 实际文件结构</h1><p>仅展示当前公开结构；文件树不是执行遵守证明</p>
<label>筛选文件 <input id="query" type="search"></label><button id="expand">全部展开</button><button id="collapse">全部折叠</button><ul id="tree">'''+tree_html(items)+'''</ul>
<script>const q=document.getElementById('query');q.addEventListener('input',()=>{document.querySelectorAll('.file').forEach(x=>x.hidden=!x.textContent.toLowerCase().includes(q.value.toLowerCase()));if(q.value)document.querySelectorAll('details').forEach(x=>x.open=true)});document.getElementById('expand').onclick=()=>document.querySelectorAll('details').forEach(x=>x.open=true);document.getElementById('collapse').onclick=()=>document.querySelectorAll('details').forEach(x=>x.open=false);</script></html>'''
    (FRAMEWORK_ROOT/'generated/TREE.html').write_text(page,encoding='utf-8',newline='\n');print('PASS: deterministic expandable tree rendered')
if __name__=='__main__':main()
