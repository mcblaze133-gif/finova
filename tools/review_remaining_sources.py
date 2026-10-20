"""Render actual source statement pages for review, with no OCR assumptions."""
import subprocess
from pathlib import Path
from backend import storage

def main():
    renderer=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe'
    out=storage.PROJECT_DIR/'tmp/case-review/images';out.mkdir(exist_ok=True)
    for doc,page in ((8,8),(136,118),(195,253),(198,13)):
        row=storage.rows('SELECT local_path FROM documents WHERE id=?',(doc,))[0]
        subprocess.run([str(renderer),'-f',str(page),'-l',str(page),'-singlefile','-scale-to','1800','-png',str(storage.PROJECT_DIR/row['local_path']),str(out/str(doc))],check=True,capture_output=True,timeout=60)
    print(out)
if __name__=='__main__':main()
