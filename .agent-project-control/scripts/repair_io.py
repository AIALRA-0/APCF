# APCF-META {"schema":1,"visibility":"public"}
"""Small shared primitives. Locks coordinate cooperating processes, not adversarial users."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile
import time


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def normalized(text: str) -> str:
    return text.lstrip('\ufeff').replace('\r\n', '\n').replace('\r', '\n')


def text_digest(text: str) -> str:
    return digest(normalized(text).encode('utf-8'))


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def linked(path: Path) -> bool:
    path = Path(path)
    if path.is_symlink():
        return True
    try:
        return bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)
    except FileNotFoundError:
        return False


def inside(root: Path, raw: str, *, must_exist=False) -> Path:
    root = Path(root).resolve()
    if not isinstance(raw, str) or not raw or '\\' in raw:
        raise ValueError('expected a nonempty POSIX-relative path')
    rel = Path(raw)
    if rel.is_absolute() or any(p in {'', '.', '..'} for p in raw.split('/')) or ':' in raw:
        raise ValueError('unsafe relative path: ' + raw)
    p = root
    for part in rel.parts:
        p = p / part
        if linked(p):
            raise ValueError('symlink/reparse point is outside the allowed write contract: ' + raw)
    if not p.resolve().is_relative_to(root):
        raise ValueError('path escapes root: ' + raw)
    if must_exist and not p.is_file():
        raise ValueError('missing file: ' + raw)
    return p


def atomic(path: Path, data: bytes, *, expected: bytes | None = None, compare=False) -> None:
    path = Path(path)
    if linked(path):
        raise ValueError('refusing symlink write')
    path.parent.mkdir(parents=True, exist_ok=True)
    if compare and (path.read_bytes() if path.exists() else None) != expected:
        raise ValueError('concurrent/external edit: ' + str(path))
    fd, name = tempfile.mkstemp(prefix='.'+path.name+'.', dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        if compare and (path.read_bytes() if path.exists() else None) != expected:
            raise ValueError('concurrent/external edit before replace')
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def exclusive(path: Path, data: bytes) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(data); stream.flush(); os.fsync(stream.fileno())


def private_json(path: Path, value, *, create=False):
    if create and any(p.exists() or linked(p) for p in (path,path.with_name(path.name+'.apcf-meta.yaml'))):
        raise FileExistsError('record or metadata already exists; no partial creation')
    payload = canonical(value) + b'\n'
    (exclusive if create else atomic)(path, payload)
    meta = ('# APCF-META {"schema":1,"visibility":"private"}\n'
            'schema: 1\nvisibility: private\nsha256: '+digest(payload)+'\n').encode()
    (exclusive if create else atomic)(path.with_name(path.name+'.apcf-meta.yaml'), meta)


@contextlib.contextmanager
def lock(path: Path, timeout: float = 30):
    """OS advisory lock released on process death. Never silently recover by deleting it."""
    path = Path(path)
    if linked(path) or any(linked(p) for p in path.parents):
        raise ValueError('unsafe lock path')
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = path.open('a+b')
    stream.seek(0, 2)
    if stream.tell() == 0:
        stream.write(b'\0'); stream.flush()
    until = time.monotonic()+timeout
    try:
        while True:
            try:
                stream.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except (OSError, BlockingIOError):
                if time.monotonic() >= until:
                    raise TimeoutError('workspace busy; another operation owns the lock')
                time.sleep(.05)
        yield
    finally:
        try:
            stream.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        stream.close()
