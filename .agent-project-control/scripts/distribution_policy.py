# APCF-META {"schema":1,"visibility":"public"}
"""One explicit Core-member list shared by installation and distribution."""
from __future__ import annotations
import json
from pathlib import Path
import shutil
from repair_io import inside, linked
from common import parse_meta

GENERATED_FACTS={'.agent-project-control/PROJECT.md': '# 1. 项目知识\n\n尚未调查当前项目；接入后只写真实目标、范围、约束和现有权威引用，不继承源模板的业务事实；\n',
                 '.agent-project-control/ARCHITECTURE.md': '# 1. 架构知识\n\n尚未调查当前项目；接入后按真实源码记录模块、依赖、数据与部署关系，不虚构架构；\n',
                 '.agent-project-control/DESIGN.md': '# 1. 项目设计知识\n\n共享 D01–D16 正文位于 design/RULES.md，项目只维护实际采用及例外；\n\n- **采用状态**：`UNRESOLVED`\n- **当前 Profile**：`none`\n- **Profile 状态**：`UNRESOLVED`\n\n先调查原项目设计系统；默认不改变 UI，不自动采用示例样式；\n'}
ROOT_INSTALL={'AGENTS.md','CURRENT.md','APCF-START.md','.codex/.apcf-dir.yaml','.codex/skills/.apcf-dir.yaml'}
OPERATIONAL={'iterations','regressions','decisions','runbooks','materials','runtime'}

RUNTIME_MARKERS={'.agent-project-control/runtime/.apcf-dir.yaml', *{f'.agent-project-control/runtime/{n}/.apcf-dir.yaml' for n in ('testbed','runs','downloads','tmp','cache','large','distribution')}}

def scaffold(rel):
    parts=Path(rel).parts
    if rel in {'.codex/.apcf-dir.yaml','.codex/skills/.apcf-dir.yaml'}:
        return '# APCF-META {"schema":1,"visibility":"public"}\nschema: 1\nvisibility: public\n'
    if rel in RUNTIME_MARKERS:
        return '# APCF-META {"schema":1,"visibility":"private"}\nschema: 1\nvisibility: private\n'
    if len(parts)==3 and parts[0]=='.agent-project-control' and parts[1] in OPERATIONAL:
        if parts[2]=='.apcf-dir.yaml':return '# APCF-META {"schema":1,"visibility":"public"}\nschema: 1\nvisibility: public\n'
        if parts[2]=='INDEX.md':return '<!-- APCF-META {"schema":1,"visibility":"public"} -->\n# 1. 当前项目索引\n\n尚未建立项目实例\n'
    return None


def members(root:Path):
    p=root/'.agent-project-control/core-members.json'
    if linked(p): raise ValueError('unsafe member policy')
    obj=json.loads(p.read_text())
    rows=obj.get('files')
    if obj.get('schema')!=1 or not isinstance(rows,list) or len(set(rows))!=len(rows) or not rows:
        raise ValueError('invalid or empty explicit Core member policy')
    for rel in rows:
        inside(root,rel)
        parts=Path(rel).parts
        if '.git' in parts or 'node_modules' in parts or '.venv' in parts: raise ValueError('forbidden member in Core policy')
    return rows


def copy_core(root:Path,target:Path,*,install_only=False):
    rows=members(root)
    chosen=[rel for rel in rows if not install_only or rel in ROOT_INSTALL or rel.startswith('.agent-project-control/')]
    # Preflight all selected bytes before writing. Unknown/private source objects never join the set.
    for rel in chosen:
        p=inside(root,rel,must_exist=True)
        if scaffold(rel) is not None or rel in GENERATED_FACTS:continue  # source facts are deliberately not installed
        side=p.with_name(p.name+'.apcf-meta.yaml')
        meta=parse_meta(p) or parse_meta(side)
        if side.is_file():
            import hashlib,re
            match=re.search(r'^sha256: ([0-9a-f]{64})$',side.read_text(encoding='utf-8'),re.M)
            if match and match.group(1)!=hashlib.sha256(p.read_bytes()).hexdigest():raise ValueError('source metadata SHA mismatch: '+rel)
        runtime_marker=rel in RUNTIME_MARKERS
        if not meta or (meta.get('visibility')!='public' and not runtime_marker):
            raise ValueError('Core member lacks an approved public classification: '+rel)
        for parent in p.parents:
            if parent==root:break
            if linked(parent):raise ValueError('unsafe member ancestor')
            if parent.is_relative_to(root):
                directory_meta=parse_meta(parent/'.apcf-dir.yaml')
                if directory_meta and directory_meta.get('visibility')=='private' and not runtime_marker:
                    raise ValueError('public file inside a private directory: '+rel)
    for rel in chosen:
        destination=inside(target,rel)
        destination.parent.mkdir(parents=True,exist_ok=True)
        if scaffold(rel) is not None:
            destination.write_text(scaffold(rel),encoding='utf-8',newline='\n')
        elif rel in GENERATED_FACTS:
            destination.write_text('<!-- APCF-META {"schema":1,"visibility":"public"} -->\n'+GENERATED_FACTS[rel],encoding='utf-8',newline='\n')
        else: shutil.copyfile(root/rel,destination)
    return chosen
