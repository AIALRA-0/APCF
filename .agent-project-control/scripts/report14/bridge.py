# APCF-META {"schema":1,"visibility":"public"}
"""Narrow adapters for observed native APCF APIs; legacy histories use original validators."""
from __future__ import annotations
import json
from pathlib import Path
import re
from .contract import sha,normalize,SECTIONS,EMPTY
from .bindings import is14,report_text,current_bytes,published_meta,load_context,safe_turn
from .markdown import parse,body,inline,fields
from .validate import validate


def sections(report,with_offsets=False):
    doc=parse(report);order=[];out={}
    offsets=[0]
    for line in doc.lines:offsets.append(offsets[-1]+len(line))
    for s in doc.sections:
        order.append(s.number)
        out[s.number]=(s.title,body(doc,s).strip(),offsets[s.line],offsets[s.end]) if with_offsets else (s.title,body(doc,s).strip())
    return order,out

def keypoints(report):
    doc=parse(report);s=next((s for s in doc.sections if s.number==11),None)
    if not s:return []
    # Both approved title forms precede the same fact/meaning fields. The typed
    # renderer emits a bold title without an inline colon; keep legacy titles.
    titles=[i for i,n in enumerate(s.nodes) if n.type=='paragraph' and re.fullmatch(r'\*\*[^\n]+\*\*',inline(n)) and inline(n).strip('*').strip()]
    out=[]
    for i,j in zip(titles,titles[1:]+[len(s.nodes)]):
        rows=fields(s.nodes[i+1:j])
        if [r['name'] for r in rows]!=['关键事实','实际含义'] or any(not r['value'].strip() for r in rows):continue
        a=s.nodes[i].map[0];b=s.nodes[j].map[0] if j<len(s.nodes) else s.end
        out.append(''.join(doc.lines[a:b]).strip())
    return out

def native_validation(report,tr):
    try:
        tr=Path(tr)
        # Resolve against native installed root, not a guessed worktree parent.
        from common import ROOT
        root=Path(ROOT)
        ctx=load_context(root,tr)
        receipt_path=tr/'evidence/report-quality-publication.json'
        if receipt_path.is_file():
            from report_bridge.contract import validate as typed_validate,digest,text_digest
            from report_bridge.render import verify_artifact
            from report_bridge.native import sources_unchanged
            receipt=json.loads(receipt_path.read_text('utf-8-sig'))
            archive=__import__('repair_io').inside(root,receipt['snapshot_path'],must_exist=True)
            snapshot=json.loads(archive.read_text('utf-8-sig'))['snapshot']
            verify_artifact(report_text(report),snapshot)
            errors=[x.code for x in typed_validate(snapshot) if x.severity=='error']
            if digest(snapshot)!=receipt['report_digest'] or not sources_unchanged(root,snapshot['native_sources']):errors.append('typed native source binding changed')
        else:errors=[f'{x.code}: {x.message}' for x in validate(report,ctx).findings if x.severity=='error']
        # Keep genuine author review and writing activation as business-closeout checks.
        source=(tr/'TEST.md').read_text('utf-8-sig')
        if 'APCF-TEST-FORMAT v3' in source or 'APCF-FACTS ' in source:
            from prose_review import validate_review_file
            errors+=validate_review_file(report,tr)
        try:import writing_guard
        except ModuleNotFoundError:writing_guard=None
        if writing_guard is not None:errors+=writing_guard.report_errors(report,tr)
        return errors
    except Exception as exc:return ['report14 native source/review unavailable: '+type(exc).__name__]

def _state_errors_unlocked(root,require_tracked=False):
    from repair_io import inside
    try:
        root=Path(root).resolve();current=inside(root,'CURRENT.md',must_exist=True)
        text=current.read_text('utf-8-sig');meta=published_meta(text)
        if not meta:return ['CURRENT missing report14 binding']
        errors=[]
        rel=meta.get('source_turn')
        typed_receipt=(root/rel/'evidence/report-quality-publication.json') if rel else None
        if typed_receipt and typed_receipt.is_file():
            from report_bridge.contract import validate as typed_validate,digest,text_digest
            receipt=json.loads(typed_receipt.read_text('utf-8-sig'))
            archive=inside(root,receipt['snapshot_path'],must_exist=True)
            snapshot=json.loads(archive.read_text('utf-8-sig'))['snapshot']
            if digest(snapshot)!=receipt['report_digest'] or text_digest(report_text(text))!=receipt['markdown_sha256']:errors.append('typed report identity mismatch')
            errors += [x.code for x in typed_validate(snapshot) if x.severity=='error']
            from report_bridge.render import verify_artifact
            verify_artifact(report_text(text),snapshot)
        else:errors=[x.code for x in validate(report_text(text)).findings]
        rel=meta.get('source_turn')
        if rel is None:
            if meta.get('kind')!='initial':errors.append('initial state identity missing')
            return errors
        turn=inside(root,rel)
        if not rel.startswith('.agent-project-control/iterations/') or turn.parent.name!='turns':return errors+['invalid Source TURN']
        required=[turn/'TURN.md',turn/'CHECKLIST.md',turn/'TEST.md',turn.parents[1]/'ITERATION.md']
        for p in required:
            if not p.is_file():errors.append('missing durable source '+p.name)
        if errors:return errors
        if report_text(text)!=report_text(required[0].read_text('utf-8-sig')):errors.append('CURRENT/TURN report mismatch')
        index=root/'.agent-project-control/iterations/INDEX.md'
        if not index.is_file() or turn.parents[1].name not in index.read_text('utf-8-sig'):errors.append('current IT not indexed')
        if require_tracked:
            import state_integrity
            for p in [current,index,*required]:
                if not state_integrity._git_tracked(p):errors.append('untracked or modified durable source '+p.name)
        return errors
    except Exception as exc:return ['CURRENT binding could not be checked: '+type(exc).__name__]

def state_errors(root,require_tracked=False):
    from .storage import Store
    store=Store(root)
    try:
        with store.guard():
            store._recover()
            return _state_errors_unlocked(root,require_tracked)
    except Exception as exc:return ['state checkpoint temporarily unavailable: '+type(exc).__name__]

def install(kind,g):
    """Invoked once at end of each patched native module; original functions retained."""
    if kind=='report_contract':
        oldsplit=g['split_sections'];oldvalidate=g['validate_report']
        g['split_sections']=lambda report:sections(report) if is14(report) else oldsplit(report)
        g['validate_report']=lambda report,turn_dir:native_validation(report,turn_dir) if is14(report) else oldvalidate(report,turn_dir)
    elif kind=='finalize_turn':
        oldbuild=g['_build_current'];oldmatch=g['_current_matches_turn']
        def build(tr,report):
            return current_bytes(report,Path(tr).relative_to(g['ROOT']).as_posix(),kind='finalized') if is14(report) else oldbuild(tr,report)
        def match(current,tr,turn):
            if current is not None:
                try:
                    txt=current.decode('utf-8-sig')
                    if is14(txt):
                        m=published_meta(txt)
                        return m.get('source_turn')==Path(tr).relative_to(g['ROOT']).as_posix() and report_text(txt)==report_text(turn.decode('utf-8-sig'))
                except Exception:return False
            return oldmatch(current,tr,turn)
        g['_build_current']=build;g['_current_matches_turn']=match
        oldfinal=g['_finalize']
        def finalize(tr):
            from .storage import Store
            store=Store(g['ROOT'])
            with store.guard():
                store._recover()
                return oldfinal(tr)
        g['_finalize']=finalize
    elif kind=='state_integrity':
        old=g['validate']
        def check(require_tracked=False):
            p=g['ROOT']/'CURRENT.md'
            if p.is_file() and is14(p.read_text('utf-8-sig')):return state_errors(g['ROOT'],require_tracked)
            return old(require_tracked)
        g['validate']=check
    elif kind=='terminology_review':
        oldextract=g['extract_user_report'];oldsections=g['report_sections'];oldmask=g['_report_without_glossary'];oldgloss=g['glossary_lines']
        def extract(text):
            if is14(text):
                p=report_text(text)
                if [s.number for s in parse(p).sections]!=list(range(1,15)):raise ValueError('incomplete report14')
                return p.strip()
            return oldextract(text)
        def mask(report):
            if not is14(report):return oldmask(report)
            _,ss=sections(report,True);_,b,a,e=ss[3]
            return report[:a]+g['_blank'](report[a:e])+report[e:],[l.strip() for l in b.splitlines() if l.startswith('- ')]
        g['extract_user_report']=extract
        g['report_sections']=lambda report:sections(report,True) if is14(report) else oldsections(report)
        g['_report_without_glossary']=mask
        g['glossary_lines']=lambda report:[l.strip() for l in sections(report_text(report))[1][3][1].splitlines() if l.startswith('- ')] if is14(report) else oldgloss(report)
    elif kind=='execution_session':
        oldauthority=g['authority']
        def authority(root=None):
            root=Path(g['ROOT'] if root is None else root);out=oldauthority(root)
            for folder in (root/'.agent-project-control/reporting',root/'.agent-project-control/scripts/report14',root/'.agent-project-control/scripts/report_bridge'):
                for p in sorted(folder.rglob('*')):
                    if p.is_file() and '__pycache__' not in p.parts and p.name!='agent.local.json':out[p.relative_to(root).as_posix()]=sha(p.read_bytes())
            return out
        g['authority']=authority
        def emit(turn,request_id,output,*,observed=False):
            from report_bridge.ports import emit as emit_summary
            return emit_summary(g['ROOT'],turn,request_id,output,observed=observed)
        def legacy_emit(turn,request_id,output,*,observed=False):
            from .runtime import publish
            from repair_io import atomic,linked,private_json
            turn=g['_safe_turn'](safe_turn(g['ROOT'],turn));g['load'](turn,request_id)
            output=Path(output).absolute()
            if linked(output) or any(linked(p) for p in output.parents):raise ValueError('unsafe output target')
            control=g['CONTROL'].resolve()
            if output.resolve().is_relative_to(control) and not output.resolve().is_relative_to(turn/'evidence'):raise ValueError('unsafe control output')
            if output.resolve()==(g['ROOT']/'CURRENT.md').resolve():raise ValueError('use the managed CURRENT writer')
            if observed:
                value=report_text((turn/'TURN.md').read_text('utf-8-sig'))
                if not output.is_file() or report_text(output.read_text('utf-8-sig'))!=value:raise ValueError('captured output mismatch')
                row={'schema':1,'request_id':request_id,'report_sha256':g['text_digest'](value.strip()),'status':'OBSERVED_TEXT_MATCH'}
            else:
                result=publish(g['ROOT'],turn,request_id=request_id)
                payload=(normalize(result.report).strip()+'\n').encode()
                before=output.read_bytes() if output.exists() else None
                if before is not None and before!=payload:raise ValueError('existing output must not be overwritten')
                if before!=payload:atomic(output,payload,expected=before,compare=True)
                row={'schema':1,'request_id':request_id,'report_sha256':g['text_digest'](result.report.strip()),'status':'PREPARED_FOR_DELIVERY',
                     'output_sha256':sha(payload),'format_valid':True,'current_saved':result.saved,'business_finalized':False}
            row['transport']='caller capture only; a real host sink must be separately verified'
            private_json(turn/'evidence/delivery-text.json',row);return row
        g['emit']=emit
    elif kind=='supervisor':
        oldcontext=g['_require_context']
        def context(turn,request):
            try:return oldcontext(turn,request)
            except ValueError:
                # Accept only our same-request checkpoint; all non-CURRENT context
                # identities are rechecked. This is not a business Finalize receipt.
                bound=g['_binding'](turn,request);row=g['_latest'](turn,request,'context')
                if row is None or any(row['facts'].get(k)!=v for k,v in bound.items()):raise
                stopped=g['_latest'](turn,request,'interrupt')
                if stopped and stopped['sequence']>row['sequence']:raise
                for rel,digest in row['facts']['files'].items():
                    p=g['ROOT']/rel
                    if rel!='CURRENT.md' and sha(p.read_bytes())!=digest:raise ValueError('context source changed')
                meta=published_meta((g['ROOT']/'CURRENT.md').read_text('utf-8-sig'))
                if meta.get('request_id')!=request or meta.get('source_turn')!=Path(turn).relative_to(g['ROOT']).as_posix() or state_errors(g['ROOT']):raise
                return bound
        g['_require_context']=context
        def prepare(turn,request,output):
            turn=g['_turn'](turn)
            receipt=g['session'].emit(turn,request,output)
            return g['_append'](turn,request,'prepare-output','PASS',{**receipt,'scope':'report structure; not business acceptance'})
        def observe(turn,request,captured):
            turn=g['_turn'](turn);g['session'].load(turn,request)
            receipt=g['session'].emit(turn,request,captured,observed=True)
            return g['_append'](turn,request,'captured-output','PASS',{**receipt,'transport_scope':'caller capture; real host verification required'})
        g['prepare']=prepare;g['observe_output']=observe
    elif kind=='writing_guard':
        # The native guard selects section 3 for fourteen chapters and retains
        # its carrier, naming and protected-text checks; do not replace those
        # checks with the older report validator's required-English-title rule.
        pass
    elif kind=='bootstrap':
        old=g['write_md']
        def write(path,text,*a,**k):
            if Path(path).name=='CURRENT.md' and '尚未开始项目执行轮次' in text:
                from repair_io import atomic
                from .render import render,blank_model
                atomic(Path(path),current_bytes(render(blank_model()),None,kind='initial'));return
            return old(path,text,*a,**k)
        g['write_md']=write
    elif kind=='routing_receipt':
        old=g['authority_paths']
        def paths(*a,**k):
            out=list(old(*a,**k));root=Path(g['ROOT'])
            for folder in (root/'.agent-project-control/reporting',root/'.agent-project-control/scripts/report14',root/'.agent-project-control/scripts/report_bridge'):
                out.extend(p for p in folder.rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.name!='agent.local.json')
            return sorted(set(out))
        g['authority_paths']=paths
    elif kind=='gate_check':
        old=g['_markdown_prose']
        def prose(text):
            # The user-approved reference is a byte-bound source quotation,
            # not editable generated prose. Keep all content-review obligations;
            # exempt only this exact source from the editable-punctuation scan.
            from .contract import HOME,verify_authority
            try:
                if verify_authority() and text==(HOME/'APPROVED-REFERENCE.md').read_text('utf-8'):
                    return []
            except OSError:
                pass
            return old(text)
        g['_markdown_prose']=prose
