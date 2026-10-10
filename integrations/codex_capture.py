# APCF-META {"schema":1,"visibility":"public"}
#!/usr/bin/env python3
"""Opt-in Codex CLI capture adapter; gates only this process's final stdout.

Prerequisite: a real installed project with a current APCF request/plan lifecycle.
Uses public codex exec JSONL and last-message flags, validated against local help.
It never adds approval-bypass flags, cannot police other shells or desktop chat,
and cannot authenticate an adversarial same-user CLI or human acknowledgement.
Sources: openai/codex codex-rs/exec/src/{cli.rs,exec_events.rs}; see docs/HOST.md.
"""
from __future__ import annotations
import argparse
from datetime import datetime,timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

MAX_CAPTURE = 256*1024*1024

def norm(s):return s.replace('\r\n','\n').replace('\r','\n').strip()
def sha(b):return hashlib.sha256(b).hexdigest()
def safe(path):
    path=Path(path).absolute()
    for p in (path,*path.parents):
        if p.is_symlink() or (p.exists() and getattr(p.lstat(),'st_file_attributes',0)&0x400):
            raise ValueError('symlinks/reparse paths are not accepted for capture')
    return path.resolve()

def parse_events(data:bytes):
    """Read a completed CLI turn, including the actual last agent-message event.

    Extra known/unknown telemetry events are retained in raw capture, not used as
    a substitute for terminal success. A failed or truncated turn never releases.
    """
    if len(data)>MAX_CAPTURE:raise ValueError('capture exceeds inspected size limit')
    rows=[]
    for raw in data.decode('utf-8').splitlines():
        if raw.strip():
            v=json.loads(raw)
            if not isinstance(v,dict):raise ValueError('event is not an object')
            rows.append(v)
    if not rows or any(r.get('type') in ('error','turn.failed') for r in rows):
        raise ValueError('CLI event stream contains fatal errors or is empty')
    started=[i for i,r in enumerate(rows) if r.get('type')=='turn.started']
    complete=[i for i,r in enumerate(rows) if r.get('type')=='turn.completed']
    if len(started)!=1 or len(complete)!=1 or complete[0]<=started[0]:
        raise ValueError('exactly one completed invocation is required')
    messages=[(i,r['item'].get('text')) for i,r in enumerate(rows)
        if r.get('type')=='item.completed' and isinstance(r.get('item'),dict)
        and r['item'].get('type')=='agent_message']
    if not messages or not started[0]<messages[-1][0]<complete[0] or not isinstance(messages[-1][1],str):
        raise ValueError('no final agent message before completion')
    # Never accept post-completion output silently.
    if any(r.get('type') in ('item.completed','turn.started','turn.failed') for r in rows[complete[0]+1:]):
        raise ValueError('unexpected output after completed turn')
    threads=[r.get('thread_id') for r in rows if r.get('type')=='thread.started']
    return messages[-1][1],threads[-1] if threads else None

def checked_capture(raw:bytes,last:bytes,expected_thread=None):
    text,thread=parse_events(raw)
    if expected_thread is not None and thread!=expected_thread:
        raise ValueError('captured thread differs from the requested resume identity')
    if not last or norm(last.decode('utf-8'))!=norm(text):
        raise ValueError('CLI last-message file differs from the captured agent event')
    return text,thread

def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--project',required=True);ap.add_argument('--turn',required=True)
    ap.add_argument('--request-id',required=True);ap.add_argument('--capture-dir',required=True)
    ap.add_argument('--codex',default='codex');ap.add_argument('--thread-id')
    ap.add_argument('--sandbox',choices=['read-only','workspace-write'],default='read-only')
    ap.add_argument('--timeout',type=int,default=1800)
    a=ap.parse_args();out=None;receipt={};created_output=False
    try:
        root=safe(a.project);out=safe(a.capture_dir)
        if out.exists() or out.is_relative_to(root) or root.is_relative_to(out) or not out.parent.is_dir():
            raise ValueError('capture must be a new directory outside the project')
        scripts=root/'.agent-project-control/scripts'
        if not (scripts/'supervisor.py').is_file():raise ValueError('current supervisor is not installed')
        executable=shutil.which(a.codex)
        if not executable:raise ValueError('Codex binary unavailable; actual host check NOT_RUN')
        version=subprocess.run([executable,'--version'],capture_output=True,timeout=20,check=True).stdout.decode('utf-8','replace').strip()
        help_args=[executable,'exec',*(['resume'] if a.thread_id else []),'--help']
        help_text=subprocess.run(help_args,capture_output=True,timeout=20,check=True).stdout.decode('utf-8','replace')
        for flag in ('--json','--output-last-message'):
            if flag not in help_text:raise ValueError('installed CLI help does not support '+flag)
        # Imported only from the inspected project; this is not a trusted remote sandbox.
        sys.path.insert(0,str(scripts));S=importlib.import_module('supervisor')
        turn=S._turn(a.turn)
        S.inspect(turn,a.request_id,project=root)
        out.mkdir(mode=0o700)
        created_output=True
        request=(turn/'REQUEST.md').read_text(encoding='utf-8')
        prompt=('请读取真实项目 AGENTS.md、当前 REQUEST/CHECKLIST/TEST、APCF_ONBOARDING.md 与 '
                'EXECUTION_SUPERVISION.md；使用当前请求身份，不另建替代请求或修改共享规则。'
                '按正式合同完成当前任务并通过既有 Gate/Finalize。最后逐字输出经 prepare 核验的完整用户正文，'
                '不要在终稿之后另写摘要。若无法完成，明确报告未完成而不伪造通过。\n'
                f'当前项目：{root}\n当前 TR：{turn}\n当前 request_id：{a.request_id}\n\n'+request)
        # No --dangerously-bypass-approvals-and-sandbox, --full-auto, --all or implicit --last.
        cmd=[executable,'exec','--sandbox',a.sandbox,'--json','--output-last-message',str(out/'last-message.md')]
        if a.thread_id:cmd += ['resume',a.thread_id,'-']
        else:cmd += ['-']
        receipt={'schema':1,'started_at':datetime.now(timezone.utc).isoformat(),'host_version':version,
                 'request_id':a.request_id,'prompt_sha256':sha(prompt.encode()),'sandbox':a.sandbox,
                 'limits':['gates adapter stdout only','unwrapped tools not intercepted','not human receipt']}
        start=time.monotonic()
        env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8')
        with (out/'events.jsonl').open('xb') as stdout,(out/'stderr.txt').open('xb') as stderr:
            try:
                r=subprocess.run(cmd,input=prompt.encode('utf-8'),stdout=stdout,stderr=stderr,cwd=root,
                                 env=env,timeout=a.timeout,check=False)
            except (subprocess.TimeoutExpired,KeyboardInterrupt):
                S.interrupt(turn,a.request_id,'CLI adapter timeout or user interruption')
                raise
        receipt['elapsed_seconds']=round(time.monotonic()-start,3);receipt['exit_code']=r.returncode
        if r.returncode:raise ValueError('Codex exited nonzero; inspect private capture, no final text released')
        if not (out/'last-message.md').is_file():raise ValueError('Codex did not save final message')
        if (out/'events.jsonl').stat().st_size>MAX_CAPTURE or (out/'last-message.md').stat().st_size>MAX_CAPTURE:
            raise ValueError('capture size exceeds audited budget; no text released')
        text,thread=checked_capture((out/'events.jsonl').read_bytes(),(out/'last-message.md').read_bytes(),a.thread_id)
        # Compare using the preloaded source; actual final Gate transaction is required.
        S.observe_output(turn,a.request_id,out/'last-message.md')
        receipt.update(status='CAPTURE_MATCHED',thread_id=thread,events_sha256=sha((out/'events.jsonl').read_bytes()),
                       final_text_sha256=sha(text.encode('utf-8')))
        (out/'adapter-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        sys.stdout.write(text);sys.stdout.flush();return 0
    except (OSError,ValueError,RuntimeError,subprocess.SubprocessError,KeyboardInterrupt) as e:
        if created_output and out and out.is_dir():
            receipt.update(status='NOT_RELEASED',reason=str(e))
            (out/'adapter-receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print('BLOCKED:',str(e),file=sys.stderr);return 2
if __name__=='__main__':raise SystemExit(main())
