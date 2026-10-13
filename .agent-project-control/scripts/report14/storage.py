# APCF-META {"schema":1,"visibility":"public"}
"""Presentation checkpoint using APCF's native lock/atomic primitives, NOT Finalize."""
from __future__ import annotations
import base64
import json
import contextlib
import threading

_HELD=threading.local()
from pathlib import Path
from .contract import sha,normalize
from .bindings import current_bytes,report_text,TURN_MARKER,unchanged,safe_turn


def _read(p):return p.read_bytes() if p.exists() else None

def _pack(data):return None if data is None else base64.b64encode(data).decode('ascii')

def _unpack(data):return None if data is None else base64.b64decode(data,validate=True)

class Store:
    def __init__(self,root:Path, *, lock_timeout=.75):
        from repair_io import inside
        # Use the native private temporary area already excluded by consumer Git.
        # Windows mandatory locks must never become business candidate inputs.
        self.root=Path(root).resolve();self.home=inside(self.root,'.agent-project-control/runtime/tmp/report14')
        self.timeout=min(2,max(0,lock_timeout));self.lock_path=self.home/'publication.lock'
        self.journal=self.home/'publication.json'
    @contextlib.contextmanager
    def guard(self):
        from repair_io import lock
        held=getattr(_HELD,'roots',set())
        if str(self.root) in held:
            yield;return
        with lock(self.lock_path,timeout=self.timeout):
            _HELD.roots=held|{str(self.root)}
            try:yield
            finally:_HELD.roots=held
    def _paths(self,tr):
        from repair_io import inside
        rel=safe_turn(self.root,tr).relative_to(self.root).as_posix()
        if not rel.startswith('.agent-project-control/iterations/'):raise ValueError('unsafe Turn')
        return inside(self.root,rel+'/TURN.md',must_exist=True),inside(self.root,'CURRENT.md'),rel
    def _recover(self):
        from repair_io import inside,atomic,private_json
        if not self.journal.is_file():return 'none'
        row=json.loads(self.journal.read_text('utf-8'))
        if row.get('schema')!=1 or row.get('state') not in ('PREPARED','COMMITTED','ROLLED_BACK'):raise ValueError('publication journal invalid')
        if row['state']!='PREPARED':return row['state']
        if row.get('root')!=str(self.root):raise ValueError('foreign publication journal')
        pending=[]
        for target in row['targets']:
            p=inside(self.root,target['path']);before=_unpack(target['before']);after=_unpack(target['after'])
            if target['before_sha256']!=(sha(before) if before is not None else None) or target['after_sha256']!=sha(after):raise ValueError('journal images invalid')
            actual=_read(p)
            if actual not in (before,after):raise ValueError('external change protected')
            pending.append((p,before,after,actual))
        # Validate all preimages first: don't partially roll back a concurrent external edit.
        for p,before,after,actual in reversed(pending):
            if actual==before:continue
            if before is None:p.unlink()
            else:atomic(p,before,expected=after,compare=True)
        row['state']='ROLLED_BACK';private_json(self.journal,row)
        return 'ROLLED_BACK'
    def recover(self):
        from repair_io import lock
        with self.guard():return self._recover()
    def publish(self,tr:Path,text:str,*,request_id='',sources=None,before_current=None,before_turn=None,fault=None,projections=None):
        from repair_io import lock,private_json,atomic,inside
        turn,current,rel=self._paths(tr)
        with self.guard():
            self._recover()
            if request_id:
                import execution_session
                execution_session.load(Path(tr),request_id)
            if sources and not unchanged(self.root,sources):raise ValueError('source changed during generation')
            oldturn=_read(turn);oldcurrent=_read(current)
            if oldturn!=before_turn or oldcurrent!=before_current:raise ValueError('publication snapshot changed')
            original=oldturn.decode('utf-8-sig');text=normalize(text).strip()+'\n'
            if original.count(TURN_MARKER)!=1:raise ValueError('missing unique Turn report slot')
            # An immutable finalized Turn can only be re-read, never rewritten by repair.
            if '- **Status**：FINALIZED' in original:
                if report_text(original)!=text:raise ValueError('finalized report immutable')
                if oldcurrent and report_text(oldcurrent.decode('utf-8-sig'))==text:return {'saved':True,'idempotent':True,'kind':'finalized'}
                raise ValueError('finalized current is not this Turn')
            ending='\r\n' if b'\r\n' in oldturn else '\n'
            newturn=oldturn if report_text(original)==text else (original.split(TURN_MARKER,1)[0]+TURN_MARKER+ending*2+text.replace('\n',ending)).encode('utf-8')
            if oldturn.startswith(b'\xef\xbb\xbf') and not newturn.startswith(b'\xef\xbb\xbf'):newturn=b'\xef\xbb\xbf'+newturn
            newcurrent=current_bytes(text,rel,request_id)
            extras=[]
            for item in projections or []:
                path=inside(self.root,item['path'])
                owned=path.parent==Path(tr)/'evidence' and __import__('re').fullmatch(r'report-quality-(?:publication|snapshot-r[1-9][0-9]*)\.json(?:\.apcf-meta\.yaml)?',path.name)
                if not (path.is_relative_to(self.home/'quality') or owned):
                    raise ValueError('projection is not a report-owned path')
                before=item['before'];after=item['after']
                if not isinstance(after,bytes) or _read(path)!=before:raise ValueError('projection snapshot changed')
                extras.append((path,before,after))
            if oldturn==newturn and oldcurrent==newcurrent and all(b==a for _,b,a in extras):return {'saved':True,'idempotent':True,'kind':'checkpoint'}
            targets=[]
            for p,b,a in ((turn,oldturn,newturn),(current,oldcurrent,newcurrent),*extras):
                targets.append({'path':p.relative_to(self.root).as_posix(),'before':_pack(b),'after':_pack(a),
                                'before_sha256':sha(b) if b is not None else None,'after_sha256':sha(a)})
            row={'schema':1,'root':str(self.root),'state':'PREPARED','request_id':request_id,
                 'report_sha256':sha(text),'sources':sources or {},'targets':targets,'kind':'report_checkpoint_not_business_finalize'}
            archive=inside(self.root,'.agent-project-control/runtime/tmp/report14/history/'+sha(text)+'.json')
            if not archive.exists():private_json(archive,{'report':text,'request_id':request_id,'sources':sources or {}})
            private_json(self.journal,row)
            for i,t in enumerate(targets):
                p=inside(self.root,t['path']);atomic(p,_unpack(t['after']),expected=_unpack(t['before']),compare=True)
                if fault:fault('after_write_'+str(i))
            if report_text(turn.read_text('utf-8-sig'))!=report_text(current.read_text('utf-8-sig')):raise ValueError('publication body mismatch')
            row['state']='COMMITTED';private_json(self.journal,row)
            return {'saved':True,'idempotent':False,'kind':'checkpoint','report_sha256':sha(text)}
    def audit(self,diagnostics):
        from repair_io import private_json
        import uuid
        try:private_json(self.home/'diagnostics'/('event-'+uuid.uuid4().hex+'.json'),diagnostics)
        except Exception:pass
