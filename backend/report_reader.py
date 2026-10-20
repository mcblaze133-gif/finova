"""View-only PDF reader. It never generates or modifies research findings."""
import asyncio,hashlib,html,json,re
from urllib.parse import urlsplit
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse,FileResponse
from backend import storage
LOCKS={}

def job_and_pdf(report_id):
 from backend.analysis_reports import row
 job=row(report_id)
 if job['status'] not in ('completed','partial') or not job['pdf_path']:raise HTTPException(409,'Report is not ready.')
 path=Path(job['pdf_path']).resolve();root=(storage.PROJECT_DIR/'outputs'/report_id).resolve()
 if not path.is_relative_to(root) or not path.is_file():raise HTTPException(404,'Report unavailable.')
 return job,path

async def prepared(report_id):
 job,path=job_and_pdf(report_id);digest=await asyncio.to_thread(lambda:hashlib.sha256(path.read_bytes()).hexdigest());folder=path.parent/'reader'/digest[:16]
 async with LOCKS.setdefault(report_id,asyncio.Lock()):
  if not (folder/'manifest.json').is_file():
   runtime=json.loads((storage.PROJECT_DIR/'config/runtime.json').read_text())
   proc=await asyncio.create_subprocess_exec(runtime['pdf_python'],str(storage.PROJECT_DIR/'tools/render_web_report.py'),'--input',str(path),'--out',str(folder),stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
   try:out,err=await asyncio.wait_for(proc.communicate(),130)
   except BaseException:
    if proc.returncode is None:proc.kill();await proc.wait()
    raise
   if proc.returncode:raise HTTPException(503,'The online reader is unavailable. Download the PDF to read the report.')
 return job,folder,json.loads((folder/'manifest.json').read_text())

async def view(report_id):
 from backend.companies import resolve
 job,folder,manifest=await prepared(report_id);esc=lambda v:html.escape(str(v),quote=True);company=resolve(job['company']).legal_name
 body=[]
 for page in manifest['pages']:
  n=page['number'];overlays=[]
  for i,link in enumerate(page['links']):
   url=link['url'];parsed=urlsplit(url)
   if not re.fullmatch(r'#page-[1-9][0-9]*',url):
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.password:continue
    if parsed.scheme=='http' and parsed.hostname not in ('127.0.0.1','localhost'):continue
   style=';'.join(f'{key}:{float(link[key]):.5f}%' for key in ('left','top','width','height'))
   attrs='' if link['url'].startswith('#') else ' target="_blank" rel="noopener noreferrer"'
   overlays.append(f'<a class="source" href="{esc(link["url"])}" style="{style}" aria-label="Open reference on page {n}"{attrs}></a>')
  body.append(f'<section id="page-{n}" class="page"><img loading="lazy" width="{page["width"]}" height="{page["height"]}" src="/analysis-reports/{report_id}/pages/{n}" alt="{esc(company)} research report, page {n}">{"".join(overlays)}</section>')
 excel=f'/excel/exports/{job["export_id"]}'
 text=f'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(company)} | Finova research</title><style>
 *{{box-sizing:border-box}}body{{margin:0;background:#e7edf0;font:15px/1.5 system-ui,sans-serif;color:#172f48}}header{{position:sticky;top:0;z-index:2;background:white;border-bottom:1px solid #ccd7dd;padding:14px 24px;display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap}}h1{{font-size:18px;margin:0}}small{{color:#52636e}}nav{{display:flex;gap:12px;flex-wrap:wrap}}nav a{{color:#12695c}}main{{max-width:1000px;margin:20px auto;padding:0 16px}}.page{{position:relative;margin:18px 0;background:white;box-shadow:0 2px 12px #0002;scroll-margin-top:120px}}img{{display:block;width:100%;height:auto}}.source{{position:absolute;display:block;cursor:pointer}}.source:hover,.source:focus{{outline:2px solid #12695c;background:#12695c22}}.note{{padding:10px 0;color:#52636e;font-size:13px}}@media print{{header,.note{{display:none}}.page{{margin:0;box-shadow:none;break-after:page}}}}
 </style></head><body><header><div><h1>{esc(company)}</h1><small>Finova research · {len(manifest['pages'])} pages · Evidence limitations are stated in the report</small></div><nav><a href="/analysis-reports/{report_id}/pdf">Download PDF</a><a href="{esc(excel)}">Editable Excel</a><a href="/#report-{report_id}">Company results</a></nav></header><main><p class="note">These are the pages of the generated PDF. Select a contents entry or source reference to follow its link. Browser zoom can enlarge the pages.</p>{''.join(body)}</main></body></html>'''
 return HTMLResponse(text,headers={'Cache-Control':'no-store'})

async def page_image(report_id,page):
 job,folder,manifest=await prepared(report_id)
 if page<1 or page>len(manifest['pages']):raise HTTPException(404,'Page unavailable.')
 path=(folder/manifest['pages'][page-1]['file']).resolve()
 if not path.is_relative_to(folder.resolve()) or path.suffix!='.png' or not path.is_file():raise HTTPException(404,'Page unavailable.')
 return FileResponse(path,media_type='image/png',headers={'Cache-Control':'no-store'})
