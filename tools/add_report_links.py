"""Add native OOXML links: the bundled formula evaluator cannot cache HYPERLINK.
Only hyperlinks/relationships are added; financial cells and formulas are preserved.
"""
import json,re,os
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as E
S='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R='http://schemas.openxmlformats.org/officeDocument/2006/relationships'
P='http://schemas.openxmlformats.org/package/2006/relationships'
E.register_namespace('x',S);E.register_namespace('r',R)

def apply(path,manifest):
 links=json.loads(Path(manifest).read_text());assert len(links)<=500
 with ZipFile(path) as z:
  data={i.filename:z.read(i.filename) for i in z.infolist()};infos=z.infolist()
 wb=E.fromstring(data['xl/workbook.xml']);rels={n.get('Id'):n.get('Target') for n in E.fromstring(data['xl/_rels/workbook.xml.rels'])}
 sheets={n.get('name'):(rels[n.get('{'+R+'}id')].lstrip('/') if rels[n.get('{'+R+'}id')].startswith('/') else 'xl/'+rels[n.get('{'+R+'}id')]) for n in wb.findall('{'+S+'}sheets/{'+S+'}sheet')}
 for name in {l['sheet'] for l in links}:
  if name not in ('Dashboard','Research','Sources','Sector comparison'):raise ValueError('Unexpected hyperlink sheet.')
  sheetpath=sheets[name];root=E.fromstring(data[sheetpath]);before=E.tostring(root.find('{'+S+'}sheetData'))
  relpath=str(Path(sheetpath).parent/'_rels'/(Path(sheetpath).name+'.rels')).replace('\\','/')
  relationships=E.fromstring(data[relpath]) if relpath in data else E.Element('{'+P+'}Relationships')
  hyperlinks=root.find('{'+S+'}hyperlinks')
  if hyperlinks is None:
   hyperlinks=E.Element('{'+S+'}hyperlinks');after={'printOptions','pageMargins','pageSetup','headerFooter','rowBreaks','colBreaks','customProperties','cellWatches','ignoredErrors','smartTags','drawing','legacyDrawing','legacyDrawingHF','picture','oleObjects','controls','webPublishItems','tableParts','extLst'}
   index=next((i for i,n in enumerate(root) if n.tag.rsplit('}',1)[-1] in after),len(root));root.insert(index,hyperlinks)
  for i,link in enumerate(l for l in links if l['sheet']==name):
   cell,url=link['cell'],link['url']
   if not re.fullmatch('[A-Z]{1,3}[1-9][0-9]{0,3}',cell):raise ValueError('Invalid hyperlink cell.')
   for old in list(hyperlinks):
    if old.get('ref')==cell:hyperlinks.remove(old)
   if url=='#Research!C2':E.SubElement(hyperlinks,'{'+S+'}hyperlink',{'ref':cell,'location':'Research!C2'})
   else:
    if not re.fullmatch(r'http://127\.0\.0\.1:8000/(analysis-reports/[a-f0-9]{32}/(?:pdf\?view=true|verification(?:/view)?)|verification/[a-z0-9-]{2,60}|documents/[0-9]+/original#page=[0-9]+)',url):raise ValueError('Unexpected hyperlink destination.')
    ident='rIdFinovaLink'+str(i+1)
    for old in list(relationships):
     if old.get('Id')==ident:relationships.remove(old)
    E.SubElement(relationships,'{'+P+'}Relationship',{'Id':ident,'Type':R+'/hyperlink','Target':url,'TargetMode':'External'})
    E.SubElement(hyperlinks,'{'+S+'}hyperlink',{'ref':cell,'{'+R+'}id':ident})
  assert E.tostring(root.find('{'+S+'}sheetData'))==before,'Financial cells changed while linking'
  data[sheetpath]=E.tostring(root,encoding='utf-8',xml_declaration=True);data[relpath]=E.tostring(relationships,encoding='utf-8',xml_declaration=True)
 temp=Path(path).with_suffix('.links.tmp.xlsx')
 with ZipFile(temp,'w') as z:
  for info in infos:z.writestr(info,data.pop(info.filename))
  for name,content in data.items():z.writestr(name,content)
 os.replace(temp,path)
 return len(links)
