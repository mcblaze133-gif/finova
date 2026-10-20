"""Inspect exported OOXML and build contact sheets from authoring previews."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from PIL import Image, ImageOps, ImageDraw

def inspect(folder):
    folder = Path(folder)
    with ZipFile(folder / 'SignalAI_FMCG_Valuation.xlsx') as archive:
        assert archive.testzip() is None
        ns = {'s': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        sheets = [name for name in archive.namelist() if name.startswith('xl/worksheets/sheet') and name.endswith('.xml')]
        formulas = tables = 0
        cached = {}
        for name in sheets:
            root = ET.fromstring(archive.read(name))
            cached[name] = {cell.get('r'):cell.findtext('s:v', namespaces=ns) for cell in root.findall('.//s:c',ns)}
            for cell in root.findall('.//s:c', ns):
                assert cell.get('t') != 'e', f'Cached formula error: {name}:{cell.get("r")}'
            fs = root.findall('.//s:f', ns)
            formulas += len(fs)
            tables += sum(f.get('t') == 'dataTable' for f in fs)
        assert len(sheets) >= 17
        assert tables == 3, 'All three scenario sensitivity tables must survive XLSX export'
        # Independent read-back check of cash-flow timing, value bridges and
        # per-share dimensions. Exported formulas remain the source of results.
        import math
        report=json.loads((folder/'verification.json').read_text())
        nsr={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
             'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
        workbook=ET.fromstring(archive.read('xl/workbook.xml'))
        relationships=ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))
        targets={r.get('Id'):r.get('Target') for r in relationships}
        sheet_names={s.get('name'):targets[s.get('{'+nsr['r']+'}id')] for s in workbook.findall('s:sheets/s:sheet',nsr)}
        def data(name):
            target=sheet_names[name].lstrip('/')
            if not target.startswith('xl/'):target='xl/'+target
            return cached[target]
        market=data('Market'); shares=float(market['D20']) if market.get('D20') else None
        for scenario,expected in report.get('scenarios',{}).items():
            if not isinstance(expected.get('dcfPerShare'),(int,float)):continue
            cells=data(scenario)
            val=lambda address:float(cells[address])
            ev=sum(val(c+'39') for c in 'EFGHI')+val('E54')
            assert math.isclose(ev,val('E66'),rel_tol=1e-10)
            assert math.isclose((ev+val('E61'))/shares,val('G66'),rel_tol=1e-10)
            assert math.isclose(val('E18')*val('E37')*val('E82'),val('E39'),rel_tol=1e-10)
            assert math.isclose(val('E52')/(val('E49')-val('E46')),val('E53'),rel_tol=1e-10)
            assert math.isclose(val('E84')-val('E85'),val('E86'),abs_tol=.001)
        report_checks=bool(report.get('scenarios'))
    files = sorted(folder.glob('preview-*.png'))
    for batch in range(0, len(files), 6):
        canvas = Image.new('RGB', (1800, 2100), 'white')
        draw = ImageDraw.Draw(canvas)
        for i, filename in enumerate(files[batch:batch+6]):
            draw.text(((i % 2)*900+10, (i//2)*700+5), filename.stem, fill='black')
            thumb = ImageOps.contain(Image.open(filename).convert('RGB'), (880, 655))
            canvas.paste(thumb, ((i % 2)*900+10, (i//2)*700+30))
        canvas.save(folder / f'contact-{batch//6+1}.png')
    result = {'sheets':len(sheets), 'formula_cells':formulas, 'native_data_tables':tables,
              'cached_formula_errors':0, 'valuation_readback_checks':report_checks, 'native_excel_verified':False}
    (folder/'xlsx-verification.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(result))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('folder')
    inspect(parser.parse_args().folder)
