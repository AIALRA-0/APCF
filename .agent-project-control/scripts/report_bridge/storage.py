# APCF-META {"schema":1,"visibility":"public"}
from __future__ import annotations
import contextlib, hashlib, json, os, shutil, tempfile, time
from pathlib import Path
from .contract import VERSION,ContractError,canonical,digest,validate
from .render import render,chat_digest


def atomic(path:Path,data:bytes):
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',dir=path.parent)
    try:
        with os.fdopen(fd,'wb') as f:f.write(data);f.flush();os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):os.unlink(name)

@contextlib.contextmanager
def lock(root:Path,timeout=3):
    root.mkdir(parents=True,exist_ok=True);path=root/'.publish.lock';deadline=time.monotonic()+timeout
    fd=None;owned_stat=None;acquired=False
    try:
        while True:
            try:
                fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);acquired=True;owned_stat=path.lstat()
                fd_stat=os.fstat(fd)
                if not os.path.samestat(owned_stat,fd_stat):
                    owned_stat=None
                    raise ContractError('LOCK_OWNERSHIP_CHANGED')
                break
            except FileExistsError:
                if time.monotonic()>deadline:raise ContractError('LOCK_TIMEOUT')
                time.sleep(.025)
        data=canonical({'pid':os.getpid(),'created_at_ns':str(time.time_ns())})
        remaining=memoryview(data)
        while remaining:
            written=os.write(fd,remaining)
            if written<=0:raise OSError('short lock metadata write')
            remaining=remaining[written:]
        current_fd=fd;fd=None;os.close(current_fd)
        yield
    finally:
        try:
            if fd is not None:
                current_fd=fd;fd=None;os.close(current_fd)
        finally:
            if acquired:
                try:current_stat=path.lstat()
                except FileNotFoundError:pass
                else:
                    if owned_stat is not None and os.path.samestat(owned_stat,current_stat):path.unlink(missing_ok=True)


def read_pointer(root:Path):
    p=root/'current.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else None


def publish(root:Path,snapshot:dict,*,quality='unreviewed',expected_revision=0,ack_locator=None,fault=None)->dict:
    if (root/'AGENTS.md').exists() or (root/'.agent-project-control').exists():
        raise ContractError('MANAGED_PROJECT_REQUIRES_NATIVE_TRANSACTION')
    """Immutable revision + commit pointer. Root CURRENT.md is recoverable mirror.

    This is a report projection transaction, not APCF Finalize, AEMP Result,
    native Run completion, execution permission or Reconciliation apply.
    """
    if quality not in ['unreviewed','needs_review','reviewed']:raise ContractError('QUALITY_STATE')
    if any(x.severity=='error' for x in validate(snapshot)):raise ContractError('INVALID_REPORT')
    md=render(snapshot);sha=digest(snapshot);rev=snapshot['revision'];ident=snapshot['identity']
    if rev!=expected_revision+1:raise ContractError('REVISION_NOT_SEQUENTIAL')
    # Revision directory is scoped by project/producer/IT/TR in the caller. Identity
    # is checked again against previous pointer to prevent accidental shared roots.
    with lock(root):
        previous=read_pointer(root)
        if previous and previous['identity']!=ident:raise ContractError('STORE_IDENTITY_MISMATCH')
        if previous and previous['revision']==rev and previous['digest']==sha:
            recover(root);return previous
        actual=previous['revision'] if previous else 0
        if actual!=expected_revision:raise ContractError('REVISION_CONFLICT')
        name=f'{rev:08d}-{sha}';target=root/'revisions'/name
        if target.exists():
            if (target/'REPORT.json').read_bytes()!=canonical(snapshot):raise ContractError('IMMUTABLE_CONFLICT')
        else:
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=Path(tempfile.mkdtemp(prefix='.pending-',dir=target.parent))
            try:
                (temp/'REPORT.json').write_bytes(canonical(snapshot))
                (temp/'CURRENT.md').write_bytes(md.replace('\n','\r\n').encode('utf-8'))
                (temp/'CHAT.md').write_text(chat_digest(snapshot,ack_locator,quality),encoding='utf-8')
                (temp/'QUALITY.json').write_bytes(canonical({'quality':quality,'report_digest':sha}))
                for p in temp.iterdir():
                    with p.open('r+b') as f:os.fsync(f.fileno())
                if fault:fault('before_revision_rename')
                os.replace(temp,target)
            finally:
                if temp.exists():shutil.rmtree(temp)
        pointer={'schema':VERSION,'revision':rev,'digest':sha,'identity':ident,'relative_dir':'revisions/'+name,'quality':quality}
        if fault:fault('before_pointer')
        atomic(root/'current.json',canonical(pointer))
        if fault:fault('after_pointer')
        recover(root)
        return pointer


def recover(root:Path)->dict|None:
    if (root/'AGENTS.md').exists() or (root/'.agent-project-control').exists():
        raise ContractError('MANAGED_PROJECT_REQUIRES_NATIVE_TRANSACTION')
    pointer=read_pointer(root)
    if not pointer:return None
    target=root/pointer['relative_dir']
    report=json.loads((target/'REPORT.json').read_text(encoding='utf-8'))
    if digest(report)!=pointer['digest']:raise ContractError('REVISION_CONTENT_CHANGED')
    for name in ['CURRENT.md','CHAT.md']:
        atomic(root/name,(target/name).read_bytes())
    return pointer


def envelope(snapshot:dict,quality:str)->dict:
    body={'schema':VERSION,'mode':'observe','identity':snapshot['identity'],'revision':snapshot['revision'],
          'source_digest':snapshot['source_digest'],'report_digest':digest(snapshot),'quality':quality,'report':snapshot}
    return {**body,'envelope_digest':digest(body)}


def enqueue(root:Path,payload:dict)->Path:
    # No credentials in an observation file. Transport credentials remain in environment.
    key=payload['envelope_digest'];path=root/'outbox'/f'{key}.json'
    if path.exists() and path.read_bytes()!=canonical(payload):raise ContractError('OUTBOX_CONFLICT')
    atomic(path,canonical(payload));return path


def verify_envelope(value:dict,expected_identity:dict|None=None)->dict:
    if not isinstance(value,dict) or value.get('schema')!=VERSION or value.get('mode')!='observe':raise ContractError('ENVELOPE_VERSION')
    if set(value)!={'schema','mode','identity','revision','source_digest','report_digest','quality','report','envelope_digest'}:raise ContractError('ENVELOPE_FIELDS')
    unsigned={k:v for k,v in value.items() if k!='envelope_digest'}
    if digest(unsigned)!=value['envelope_digest']:raise ContractError('ENVELOPE_DIGEST')
    report=value['report']
    if digest(report)!=value['report_digest'] or report['identity']!=value['identity'] or report['revision']!=value['revision'] or report['source_digest']!=value['source_digest']:raise ContractError('ENVELOPE_BINDING')
    if expected_identity and expected_identity!=value['identity']:raise ContractError('ENVELOPE_IDENTITY')
    if any(x.severity=='error' for x in validate(report)):raise ContractError('ENVELOPE_REPORT')
    return report
