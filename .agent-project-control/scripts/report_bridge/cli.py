# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import argparse,json,sys
from pathlib import Path
from .contract import validate,canonical,digest
from .quality import assess
from .render import render
from .storage import publish,envelope,enqueue
from .guidance import compile_reference


def main():
    ap=argparse.ArgumentParser();sub=ap.add_subparsers(dest='action',required=True)
    for action in ['validate','render','quality']:
        p=sub.add_parser(action);p.add_argument('input');p.add_argument('--output')
    p=sub.add_parser('index');p.add_argument('input');p.add_argument('--output',required=True)
    p=sub.add_parser('publish');p.add_argument('input');p.add_argument('--store',required=True);p.add_argument('--expected-revision',type=int,required=True)
    args=ap.parse_args()
    try:
        if args.action=='index':result=compile_reference(Path(args.input))
        else:
            obj=json.loads(Path(args.input).read_text(encoding='utf-8-sig'))
            if args.action in ['validate','quality']:
                issues=validate(obj)+(assess(obj) if args.action=='quality' else [])
                result={'structural_valid':not any(x.severity=='error' for x in issues),'semantic_quality':'not_certified','issues':[x.to_dict() for x in issues]}
            elif args.action=='render':result=render(obj)
            else:
                store=Path(args.store);result=publish(store,obj,expected_revision=args.expected_revision)
                enqueue(store,envelope(obj,result['quality']))
        payload=result if isinstance(result,str) else json.dumps(result,ensure_ascii=False,indent=2)+'\n'
        if getattr(args,'output',None):Path(args.output).write_text(payload,encoding='utf-8')
        else:sys.stdout.write(payload)
        return 0
    except Exception as exc:
        # This CLI is machine-facing; the host adapter MUST capture diagnostics.
        sys.stderr.write(json.dumps({'internal_code':type(exc).__name__,'message':str(exc)},ensure_ascii=False)+'\n');return 2

if __name__=='__main__':raise SystemExit(main())
