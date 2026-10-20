import json,tempfile,unittest
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as E
from tools.add_report_links import apply,S,R,P
class NativeLinks(unittest.TestCase):
 def fixture(self,root):
  p=root/'book.xlsx'
  with ZipFile(p,'w') as z:
   z.writestr('xl/workbook.xml',f'<x:workbook xmlns:x="{S}" xmlns:r="{R}"><x:sheets><x:sheet name="Dashboard" sheetId="1" r:id="rId1"/></x:sheets></x:workbook>')
   z.writestr('xl/_rels/workbook.xml.rels',f'<Relationships xmlns="{P}"><Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="{R}/worksheet"/></Relationships>')
   z.writestr('xl/worksheets/sheet1.xml',f'<x:worksheet xmlns:x="{S}" xmlns:r="{R}"><x:sheetData><x:row r="1"><x:c r="D1"><x:f>1+2</x:f><x:v>3</x:v></x:c></x:row></x:sheetData><x:drawing r:id="rIdChart"/></x:worksheet>')
   z.writestr('xl/worksheets/_rels/sheet1.xml.rels',f'<Relationships xmlns="{P}"><Relationship Id="rIdChart" Target="../drawings/drawing1.xml" Type="{R}/drawing"/></Relationships>')
   z.writestr('xl/drawings/drawing1.xml','untouched drawing fixture')
  return p
 def test_native_links_preserve_formulas_and_existing_chart_relationship(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);p=self.fixture(root);m=root/'links.json';m.write_text(json.dumps([{'sheet':'Dashboard','cell':'F50','url':'http://127.0.0.1:8000/analysis-reports/'+'a'*32+'/pdf?view=true'},{'sheet':'Dashboard','cell':'F51','url':'#Research!C2'}]))
   self.assertEqual(apply(p,m),2);self.assertEqual(apply(p,m),2)
   with ZipFile(p) as z:
    sheet=E.fromstring(z.read('xl/worksheets/sheet1.xml'));rels=E.fromstring(z.read('xl/worksheets/_rels/sheet1.xml.rels'))
    self.assertEqual(sheet.find('.//{'+S+'}f').text,'1+2')
    self.assertEqual(len(sheet.find('{'+S+'}hyperlinks')),2)
    self.assertIn('rIdChart',{r.get('Id') for r in rels})
    self.assertEqual(len(rels),2)
    self.assertEqual(z.read('xl/drawings/drawing1.xml'),b'untouched drawing fixture')
    self.assertLess(list(sheet).index(sheet.find('{'+S+'}hyperlinks')),list(sheet).index(sheet.find('{'+S+'}drawing')))
 def test_external_destinations_cannot_be_injected(self):
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);p=self.fixture(root);before=p.read_bytes();m=root/'links.json';m.write_text(json.dumps([{'sheet':'Dashboard','cell':'F50','url':'https://unapproved.example/'}]))
   with self.assertRaises(ValueError):apply(p,m)
   self.assertEqual(p.read_bytes(),before)
