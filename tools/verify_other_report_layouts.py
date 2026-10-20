"""Read-only PDF scope/period and layout checks; use bundled PDF Python."""
import json
import argparse
import hashlib
import math
import re
import subprocess
from pathlib import Path
import pdfplumber
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parent.parent
POPLER=Path('C:/Users/mcbla/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/poppler/Library/bin/pdftoppm.exe')

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--summary',default='reports/other-company-report-verification.json')
    parser.add_argument('--output',default='reports/other-company-report-layouts.json')
    args=parser.parse_args()
    summary=json.loads((ROOT/args.summary).read_text())
    saved=ROOT/args.output
    cache={r['company']:r for r in json.loads(saved.read_text())} if saved.exists() else {}
    checks=[]
    for item in summary['companies']:
        if not item.get('pdf_path'):continue
        path=Path(item['pdf_path']);payload=json.loads((path.parent/'research-report-inputs.json').read_text(encoding='utf-8'))
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        if cache.get(item['company'],{}).get('pdf_sha256')==digest and Path(cache[item['company']]['contact']).parent.name==digest[:12]:
            checks.append(cache[item['company']]);continue
        folder=ROOT/'tmp/pdfs/other-companies'/item['company']/digest[:12];folder.mkdir(parents=True,exist_ok=True)
        subprocess.run([str(POPLER),'-r','55','-png',str(path),str(folder/'page')],check=True,capture_output=True,timeout=120)
        bad=[];forbidden=[];historical_segments=0
        with pdfplumber.open(path) as pdf:
            text=[' '.join((p.extract_text() or '').split()) for p in pdf.pages]
            start=next(i for i,t in enumerate(text) if i>=2 and re.search(r'03\s+Historical financial',t))
            end=next(i for i,t in enumerate(text) if i>start and re.search(r'05\s+Current developments',t))
            periods=payload['history']['periods'];boundaries=[]
            for i in range(1,len(periods)):
                a,b=periods[i-1:i+1]
                if a['scope']!=b['scope'] or abs(a['duration_days']-b['duration_days'])>2 or not 300<=a['duration_days']<=370 or not 300<=b['duration_days']<=370:boundaries.append(i)
            left=48+54;right=pdf.pages[0].width-48-14
            for i,p in enumerate(pdf.pages):
                overflow=[w['text'] for w in p.extract_words() if w['x0']<46 or w['x1']>p.width-46]
                if overflow:bad.append({'page':i+1,'words':overflow})
                if start<=i<end:
                    for line in p.lines:
                        if not math.isclose(line.get('linewidth',0),2,abs_tol=.01):continue
                        if line['x1']-line['x0']<40:continue
                        historical_segments+=1
                        for b in boundaries:
                            x0=left+(right-left)*(b-1)/(len(periods)-1);x1=left+(right-left)*b/(len(periods)-1)
                            if abs(line['x0']-x0)<.2 and abs(line['x1']-x1)<.2:
                                forbidden.append({'page':i+1,'boundary':b})
            assert not forbidden,(item['company'],'graph connects incompatible reporting periods',forbidden)
            assert historical_segments>0,(item['company'],'historical trend graphs missing')
            assert not bad,(item['company'],'horizontal text overflow',bad)
            if payload.get('validation_only'):
                assert 'VALIDATION REPORT' in text[0] and 'AI ASSESSMENT NOT RUN' in text[0]
            else:
                assert 'VALIDATION REPORT' not in text[0]
            assert 'Contents' in text[1] and 'Appendix' in ' '.join(text[-8:])
        pages=sorted(folder.glob('page-*.png'));cols=6;rows=(len(pages)+cols-1)//cols
        assert len(pages)==len(text),(item['company'],'rendered page count mismatch')
        canvas=Image.new('RGB',(cols*210,rows*310),'#dfe5e9');draw=ImageDraw.Draw(canvas)
        for i,p in enumerate(pages):
            im=Image.open(p);im.thumbnail((200,285));x=i%cols*210;y=i//cols*310;canvas.paste(im,(x,y));draw.text((x+5,y+287),'Page '+p.stem.rsplit('-',1)[-1],fill='black')
        canvas.save(folder/'contact.png')
        result={'company':item['company'],'pdf_sha256':digest,'pages_rendered':len(pages),'scope_or_duration_boundaries':boundaries,
                'forbidden_chart_connections':forbidden,'horizontal_overflows':bad,'historical_chart_segments':historical_segments,
                'contact':str(folder/'contact.png')}
        checks.append(result);print(json.dumps(result),flush=True)
    saved.write_text(json.dumps(checks,indent=2),encoding='utf-8')

if __name__=='__main__':main()
