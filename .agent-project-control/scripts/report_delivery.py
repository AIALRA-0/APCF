# APCF-META {"schema":1,"visibility":"public"}
"""Public report stdout; check/context commands are explicitly internal diagnostics."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import signal
_EMERGENCY_TITLES=('精确状态头','承上启下','术语表','执行清单','文件修改','验收摘要','关键证据','结果状态','剩余限制','完整说明','关键要点','用户需要执行','需要继续讨论、搜索或决策','下一步推荐')

def emergency_report():
    return '本轮执行记录继续保留；本次报告更新尚未确认保存，暂不宣布全部工作完成\n\n完整记录见当前项目的 `CURRENT.md`\n'

try:
    from report14.contract import normalize,sha,CONTRACT,verify_authority
    from report14.bindings import report_text,load_context
    from report14.render import blank_model,render,SCHEMA
    from report14.repair import deliver
    from report14.runtime import publish,archive_note
    from report14.storage import Store
    from report14.validate import validate
except Exception as _bootstrap_error:
        # Recovery stdout remains a short truthful progress message.
    if __name__=='__main__':
        try:
            dest=Path(__file__).resolve().parents[2]/'.agent-project-control/runtime/report14/diagnostics'
            dest.mkdir(parents=True,exist_ok=True)
            (dest/'bootstrap.json').write_text(json.dumps({'internal_error':type(_bootstrap_error).__name__}),encoding='utf-8')
        except Exception:pass
        sys.stdout.buffer.write(emergency_report().encode('utf-8'))
        raise SystemExit(0)
    raise


def finalize_bounded(root,turn,timeout=25):
    """Call native transaction once, preserve its true exit code, capture all raw logs."""
    script=Path(root)/'.agent-project-control/scripts/finalize_turn.py'
    # Import/call function bypasses public transport; it does not bypass native Gate.
    code='import sys; sys.path.insert(0,sys.argv[1]); import finalize_turn; from pathlib import Path; sys.exit(finalize_turn._finalize(Path(sys.argv[2])))'
    with tempfile.TemporaryFile() as log:
        p=subprocess.Popen([sys.executable,'-B','-c',code,str(script.parent),str(turn)],cwd=root,
              stdout=log,stderr=log,start_new_session=os.name!='nt',
              creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0)
        try:p.wait(timeout=max(.1,min(60,timeout)))
        except subprocess.TimeoutExpired:
            if os.name=='nt':
                try:subprocess.run(['taskkill','/PID',str(p.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2)
                except Exception:p.kill()
            else:
                try:os.killpg(p.pid,signal.SIGKILL)
                except ProcessLookupError:pass
            p.wait(timeout=2)
        log.seek(0);raw=log.read(2_000_000).decode('utf-8','replace')
        return {'exit_code':p.returncode,'internal_log':raw}


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('command',choices=['deliver','finalize','check','context','schema'])
    ap.add_argument('--root',default=str(Path(__file__).resolve().parents[2]))
    ap.add_argument('--turn');ap.add_argument('--request-id',default='')
    inputs=ap.add_mutually_exclusive_group();inputs.add_argument('--draft');inputs.add_argument('--model');ap.add_argument('--output');ap.add_argument('--budget',type=float,default=90)
    args=ap.parse_args(argv)
    if args.command=='schema':print(json.dumps(SCHEMA,ensure_ascii=False,indent=2));return 0
    root=Path(args.root).resolve()
    if args.command in ('check','context'):
        try:
            ctx=load_context(root,Path(args.turn)) if args.turn else {}
            if args.command=='context':print(json.dumps(ctx,ensure_ascii=False,indent=2));return 0
            data=Path(args.draft).read_text('utf-8-sig');result=validate(report_text(data),ctx)
            print(json.dumps(result.json(),ensure_ascii=False,indent=2));return 0 if result.ok else 2
        except Exception as exc:print(json.dumps({'ok':False,'internal_error':type(exc).__name__}));return 2
    text=emergency_report();store=Store(root)
    try:
        if not verify_authority():raise ValueError('approved source identity changed')
        if not args.turn:raise ValueError('actual Turn required')
        turn=Path(args.turn).absolute()
        model=json.loads(Path(args.model).read_text('utf-8-sig')) if args.model else None
        draft=(model if model.get('schema')=='apcf.report-observation/1' else render(model)) if model else Path(args.draft).read_text('utf-8-sig') if args.draft else None
        result=publish(root,turn,draft,request_id=args.request_id,budget_seconds=args.budget,store=store)
        text=result.chat
        if args.command=='finalize' and result.saved:
            native=finalize_bounded(root,turn)
            store.audit({'phase':'business_finalize','native':native,'format_diagnostics':result.diagnostics})
            # The report checkpoint and business transaction are independent.
            # Preserve the same validated summary; never revert stdout to the full report.
        if args.output:
            from repair_io import atomic,linked
            output=Path(args.output).absolute()
            if output.resolve() in ((root/'CURRENT.md').resolve(),(turn/'TURN.md').resolve()) or linked(output) or any(linked(p) for p in output.parents):raise ValueError('use managed state writer')
            data=text.encode('utf-8');before=output.read_bytes() if output.exists() else None
            if before is not None and before!=data:raise ValueError('output collision')
            if before!=data:atomic(output,data,expected=before,compare=True)
    except Exception as exc:
        store.audit({'phase':'public_boundary','internal_error':type(exc).__name__})
        text=emergency_report()
    # No raw diagnostics, exception strings, prompt text or HTML state wrappers.
    if len(text)>900 or len(__import__('re').findall(r'^## \d+\. ',text,__import__('re').M))>2:text=emergency_report()
    try:sys.stdout.buffer.write(text.encode('utf-8'));sys.stdout.buffer.flush()
    except AttributeError:sys.stdout.write(text)
    return 0

if __name__=='__main__':raise SystemExit(main())
