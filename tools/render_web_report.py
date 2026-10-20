"""Render the exact generated PDF for browsers without a native PDF plug-in."""
import argparse,json,subprocess,shutil
from pathlib import Path
from pypdf import PdfReader

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
 out=Path(args.out);out.mkdir(parents=True,exist_ok=True)
 runtime_file=Path(__file__).resolve().parent.parent/'config/runtime.json'
 runtime=json.loads(runtime_file.read_text()) if runtime_file.exists() else {}
 binary=runtime.get('pdftoppm') or shutil.which('pdftoppm')
 if not binary:
  raise RuntimeError('Install Poppler on PATH or set pdftoppm in config/runtime.json.')
 subprocess.run([str(binary),'-r','110','-png',args.input,str(out/'page')],check=True,timeout=120,capture_output=True)
 reader=PdfReader(args.input);page_ids={p.indirect_reference.idnum:i+1 for i,p in enumerate(reader.pages)};pages=[]
 from urllib.parse import urlsplit
 for i,page in enumerate(reader.pages,1):
  box=page.mediabox;w,h=float(box.width),float(box.height);links=[]
  for ref in page.get('/Annots',[]):
   ann=ref.get_object();action=ann.get('/A',{});url=action.get('/URI');dest=ann.get('/Dest') or action.get('/D')
   if url:
    parsed=urlsplit(str(url))
    if parsed.scheme not in ('https','http') or parsed.username or parsed.password:continue
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost'):continue
    target=str(url)
   elif isinstance(dest,list) and dest and getattr(dest[0],'idnum',None) in page_ids:target='#page-'+str(page_ids[dest[0].idnum])
   elif isinstance(dest,str) and dest in reader.named_destinations:target='#page-'+str(reader.get_destination_page_number(reader.named_destinations[dest])+1)
   else:continue
   rect=ann.get('/Rect')
   if not rect:continue
   x0,y0,x1,y1=map(float,rect);links.append({'url':target,'left':100*x0/w,'top':100*(h-y1)/h,'width':100*(x1-x0)/w,'height':100*(y1-y0)/h})
  filename=sorted(out.glob('page-*.png'))[i-1].name
  pages.append({'number':i,'file':filename,'width':w,'height':h,'links':links})
 (out/'manifest.json').write_text(json.dumps({'pages':pages}),encoding='utf-8')
if __name__=='__main__':main()
