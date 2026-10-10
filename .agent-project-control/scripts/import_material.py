# APCF-META {"schema":1,"visibility":"public"}
import argparse,shutil,hashlib
from pathlib import Path
from common import FRAMEWORK_ROOT,next_id,now_stamp,slugify,write_md,dir_marker,meta_line
def digest(p):
    h=hashlib.sha256(); h.update(Path(p).read_bytes()); return h.hexdigest()
def _main():
    ap=argparse.ArgumentParser(); ap.add_argument('source'); ap.add_argument('--visibility',choices=['public','private'],default='private'); a=ap.parse_args(); src=Path(a.source); rid=next_id('MAT',FRAMEWORK_ROOT/'materials'); s=now_stamp(); d=FRAMEWORK_ROOT/'materials'/f'{rid}_{s}_{slugify(src.stem)}'; dir_marker(d,a.visibility); dir_marker(d/'original',a.visibility); dir_marker(d/'derived',a.visibility); dst=d/'original'/src.name; shutil.copy2(src,dst); sha=digest(dst); (dst.with_name(dst.name+'.apcf-meta.yaml')).write_text(meta_line(a.visibility,True)+f'\nschema: 1\nvisibility: {a.visibility}\nsha256: {sha}\n',encoding='utf-8'); write_md(d/'MATERIAL.md',f'# 1. {rid} {src.stem}\n\n- **Visibility**：{a.visibility}\n- **SHA-256**：`{sha}`\n',a.visibility); return d
def main():
    from repair_io import lock
    with lock(FRAMEWORK_ROOT/'runtime/tmp/.lifecycle.lock'):
        result=_main()
        from refresh_indexes import main as refresh
        refresh()
        print(result)
        return result

if __name__=='__main__': main()
