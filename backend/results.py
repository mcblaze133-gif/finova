"""Reader-facing results from saved Excel outputs, never a second valuation engine."""
import json
import math
import re
from datetime import datetime, timedelta
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import xml.etree.ElementTree as ET
from backend import storage, company_updates, evidence_packs, library, excel_engine
from backend.companies import resolve, profiles

NS = {'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def company_library():
    entries = []
    for profile in profiles().values():
        manifest = evidence_packs.read_manifest(profile.id)
        entries.append({'id':profile.id, 'legal_name':profile.legal_name,
                        'has_documents': bool(manifest and manifest.get('selected_pages')),
                        'has_valuation':bool(saved_valuation(profile.id))})
    return sorted(entries, key=lambda c:(not c['has_valuation'],not c['has_documents'], c['legal_name'].casefold()))


def reported_results(company, brief):
    result = brief.get('reported_results')
    if not result:
        return None
    source = (library.root_folder()/result['source_file']).resolve()
    if not source.is_relative_to(library.root_folder()) or not source.is_file() or evidence_packs.digest_file(source) != result['source_sha256']:
        return None
    rows = storage.rows('SELECT p.text,d.id FROM library_documents l JOIN documents d ON l.document_id=d.id JOIN passages p ON p.document_id=d.id WHERE l.company=? AND l.relative_path=? AND d.sha256=? AND p.pdf_page=?',
        (company,result['source_file'],result['source_sha256'],result['source_page']))
    if not rows:
        return None
    text = ' '.join(rows[0]['text'].split())
    if any(metric['source_value'] not in text for metric in result['metrics']):
        return None
    return {k:result[k] for k in ('period','scope','qualification','metrics')} | {
        'source_url':f'/documents/{rows[0]["id"]}/original#page={result["source_page"]}',
        'source_label':f'Supplied financial statement / presentation · PDF page {result["source_page"]}'}


def evidence_summary(company):
    manifest = evidence_packs.read_manifest(company)
    if not manifest:
        return {'status':'not_prepared'}
    fresh = evidence_packs.source_fingerprints(company) == manifest['source_fingerprints']
    unreadable = [w.split(': ',2)[1] for w in manifest.get('warnings',[]) if w.startswith('Unreadable document: ')]
    notices = []
    if any(w.startswith('No annual report identified') for w in manifest.get('warnings',[])):
        notices.append('An annual report has not been identified in the supplied documents. Full annual financial notes are still needed.')
    if any(w.startswith('Consolidated section not identified') for w in manifest.get('warnings',[])):
        notices.append('Some annual statements need review to distinguish standalone and consolidated figures.')
    if any(w.startswith('Interactive annotations omitted') for w in manifest.get('warnings',[])):
        notices.append('Printed pages are preserved. Consult the original report for interactive annotations.')
    return {'status':'ready' if fresh else 'needs_refresh', 'prepared_at':manifest['created_at'],
            'source_files':manifest.get('input_files',manifest['source_files']),
            'readable_files':manifest['source_files'], 'selected_pages':manifest['selected_pages'],
            'unreadable_files':unreadable, 'notices':notices,
            'financials_reviewed':bool(manifest.get('reviewed_records')),
            'pdf_url':f'/evidence/{company}/pdf' if fresh else None,
            'index_url':f'/evidence/{company}/download/index' if fresh else None,
            'text_url':f'/evidence/{company}/download/text' if fresh else None}


def read_saved_values(path):
    """Read saved formula values; this does not claim desktop Excel recalculation."""
    with ZipFile(path) as archive:
        if sum(i.file_size for i in archive.infolist()) > 60_000_000:
            raise ValueError('Workbook too large for results preview.')
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(si.itertext()) for si in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('s:si',NS)]
        book = ET.fromstring(archive.read('xl/workbook.xml'))
        rels = {r.get('Id'):r.get('Target') for r in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        selected = {}
        for sheet in book.findall('s:sheets/s:sheet',NS):
            if sheet.get('name') not in ('Dashboard','Market'):
                continue
            target = rels[sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            target = target.lstrip('/') if target.startswith('/') else 'xl/'+target
            cells = {}
            for cell in ET.fromstring(archive.read(target)).findall('.//s:sheetData/s:row/s:c',NS):
                raw = cell.findtext('s:v',namespaces=NS)
                if cell.get('t') == 'e':
                    cells[cell.get('r')] = None
                elif cell.get('t') == 's':
                    cells[cell.get('r')] = strings[int(raw)] if raw is not None else None
                elif cell.get('t') == 'inlineStr':
                    cells[cell.get('r')] = ''.join(cell.find('s:is',NS).itertext())
                elif raw is not None:
                    try:
                        value = float(raw)
                        cells[cell.get('r')] = value if math.isfinite(value) else None
                    except ValueError:
                        cells[cell.get('r')] = raw
            selected[sheet.get('name')] = cells
        return selected


def _date(value):
    if isinstance(value,(int,float)):
        return (datetime(1899,12,30)+timedelta(days=value)).date().isoformat()
    if isinstance(value,str):
        try:
            return datetime.fromisoformat(value.replace('Z','+00:00')).date().isoformat()
        except ValueError:
            return None
    return None


def saved_valuation(company, export_id=None):
    exports = storage.rows("SELECT * FROM excel_exports WHERE company=? AND status='exported'"+(' AND id=?' if export_id else '')+" ORDER BY created_at DESC LIMIT 8",(company,export_id) if export_id else (company,))
    for export in exports:
        path = Path(export['workbook_path'] or '').resolve()
        if not path.is_relative_to((storage.PROJECT_DIR/'outputs').resolve()) or not path.is_file():
            continue
        try:
            cells = read_saved_values(path)
            dashboard, market = cells['Dashboard'], cells['Market']
            package = json.loads(export['input_json'])
            methods = []
            for row in range(9,23):
                values = [dashboard.get(f'{c}{row}') for c in ('D','E','F')]
                if not all(isinstance(v,(int,float)) for v in values):
                    continue
                name = str(dashboard.get(f'C{row}', 'Valuation'))
                register = next((m for m in package.get('methods',[]) if
                    m['method'] == name or (name.startswith('DCF') and m['method'].startswith('DCF')) or
                    name.replace(' (stress)','') == m['method']), {})
                methods.append({'method':name, 'bear':values[0], 'base':values[1], 'bull':values[2],
                                'primary':bool(register.get('weight',0)),
                                'qualification':'Conditional cash-flow estimate' if name.startswith(('DCF','FCFE','DDM')) else 'Segment multiples are analyst assumptions' if name=='SOTP' else 'Assumed multiple; peer validation incomplete'})
            if not methods:
                continue
            weighted = {key:dashboard.get(f'{col}25') for key,col in [('bear','D'),('base','E'),('bull','F')]}
            if not all(isinstance(v,(int,float)) for v in weighted.values()):
                weighted = None
            return {'methods':methods, 'market_price':market.get('D7'), 'market_price_date':_date(market.get('D6')),
                    'weighted':weighted,
                    'valuation_date':_date(market.get('D22')), 'created_at':export['created_at'], 'download_url':f"/excel/exports/{export['id']}",
                    'qualification':'Scenario estimates depend on assumptions. Multiple-based estimates have not been independently validated against peers.',
                    'summary':_valuation_summary(methods, market.get('D7'))}
        except (ValueError,KeyError,IndexError,TypeError,BadZipFile,ET.ParseError,OSError):
            continue
    return None


def _valuation_summary(methods, price):
    dcf = next((m for m in methods if m['method'].startswith('DCF')), None)
    if not dcf or not isinstance(price,(int,float)):
        return 'Use the scenario range to judge how much the estimated value depends on business performance and valuation assumptions.'
    if price > max(dcf[k] for k in ('bear','base','bull')):
        return 'The saved market reference exceeds all three DCF estimates. This signals a large difference between the model assumptions and the market price; it does not by itself establish that the stock is overvalued.'
    if price < min(dcf[k] for k in ('bear','base','bull')):
        return 'The saved market reference is below all three DCF estimates. Check the growth, margin and risk assumptions before interpreting that difference as an investment opportunity.'
    return 'The saved market reference falls within the DCF scenario range. The investment view depends on which operating and valuation assumptions are credible.'


def company_results(company, fresh_run_id=None):
    profile = resolve(company)
    from backend import investigation
    fresh_report=None
    if fresh_run_id:
        runs=storage.rows('SELECT * FROM research_runs WHERE id=? AND company=?',(fresh_run_id,profile.id))
        if not runs or not runs[0]['report_json']:raise ValueError('The requested fresh investigation is not complete.')
        fresh_report=json.loads(runs[0]['report_json'])
        if fresh_report.get('investigation_version')!=3:raise ValueError('This is not a fresh evidence-pack investigation.')
    valuation = None if fresh_report else saved_valuation(profile.id)
    brief = storage.PROJECT_DIR/'config/company_briefs'/f'{profile.id}.json'
    brief_data = json.loads(brief.read_text(encoding='utf-8')) if brief.exists() and not fresh_report else {}
    reported = reported_results(profile.id, brief_data)
    findings = brief_data.get('findings',[]) if not brief_data.get('reported_results') or reported else []
    readiness = excel_engine.valuation_readiness(profile.id)
    latest = company_updates.get(profile.id,fresh_report['update_run_id']) if fresh_report and fresh_report.get('update_run_id') else None if fresh_report else company_updates.latest(profile.id)
    # A failed current check must not silently fall back to old assessed events.
    selected_news = latest
    news = []
    news_date = selected_news['checked_at'] if selected_news else None
    if selected_news and selected_news.get('result'):
        result = selected_news['result']
        sources = {s['source_id']:s for s in result.get('sources',[])}
        for event in result.get('events',[]):
            news.append({'headline':event['headline'], 'potential_impact':event['mechanism'],
                         'status':event.get('fact_status','Unverified news; possible impact only'),
                         'direction':event.get('direction'),'horizon':event.get('horizon'),
                         'drivers':event.get('active_model_inputs',event.get('drivers_to_review',[])),'review_action':event.get('review_action'),
                         'falsification':event.get('falsification'),
                         'sources':[{'title':sources[i]['title'],'url':sources[i]['url']} for i in event.get('source_ids',[]) if i in sources]})
        if not news:
            leads=result.get('news_leads',[])
            selected=[]
            for category in company_updates.CATEGORIES:
                match=next((lead for lead in leads if lead.get('category')==category),None)
                if match:selected.append(match)
            selected.extend(lead for lead in leads if lead not in selected)
            for lead in selected[:6]:
                news.append({'headline':lead['headline'],'potential_impact':lead.get('mechanism','Company-specific impact assessment is incomplete.'),
                    'status':'Unverified headline; impact assessment incomplete', 'drivers':lead.get('drivers_to_review',[]),
                    'review_action':'Read the original announcement and verify exposure before changing forecasts.',
                    'sources':[{'title':lead.get('publisher','News source'),'url':lead.get('url','')}]})
    reports = storage.rows('SELECT report_json FROM research_runs WHERE company=? AND report_json IS NOT NULL ORDER BY created_at DESC LIMIT 8',(profile.id,))
    if not findings and not fresh_report:
        for row in reports:
            report = json.loads(row['report_json'])
            if report.get('discovery'):
                findings = [{'title':'Financial finding','finding':report['discovery']['text'],
                             'investor_use':'Consider this alongside earnings quality, cash generation and valuation assumptions.'}]
                break
    caveats = []
    if valuation:
        caveats.append('Capital-cost and current cash/debt assumptions still need review; these are conditional estimates, not a verified price target.')
    if latest:
        caveats.append('Recent news is not independently verified and has not been automatically incorporated into numerical forecasts.')
        if latest['status'] not in ('assessed','assessed_with_unverified_sources'):
            caveats.append('The latest online check is incomplete. No absence of company developments is implied.')
        # Investor-facing coverage limits, never backend/model diagnostics.
        # Generated statements about missing material in selected excerpts are
        # not proof that the full local library lacks that material. Public
        # coverage limits are based on the recorded retrieval results instead.
        coverage=(latest.get('result') or {})
        if any(c.get('status')!='original_read' for c in coverage.get('primary_source_coverage',[])):
            caveats.append('Some original disclosures were unavailable. Recent-development coverage is incomplete.')
        if any(c.get('status')!='feed_read' for c in coverage.get('feed_coverage',[])):
            caveats.append('Some news categories could not be checked completely.')
    if valuation and profile.id=='tata-consumer':
        caveats.append('Minority put/call commitments still need a contract-level value reconciliation; minority interests currently use a carrying-value proxy.')
    if selected_news and latest and selected_news['id'] != latest['id']:
        caveats.append('The latest news update was incomplete. The dated findings from the previous completed review are shown.')
    from backend import financial_history
    return {'company':profile.legal_name,'company_id':profile.id,'valuation':valuation,'findings':findings,
            'historical_statements':financial_history.build(profile.id),
            'investigation':investigation.present(profile.id,fresh_run_id),
            'freshness':{'mode':'fresh_investigation','run_id':fresh_run_id,'started_at':fresh_report['created_at'],'completed_at':fresh_report.get('completed_at'),
                         'evidence_read_at':fresh_report.get('evidence_pack_read',{}).get('read_at'),'news_checked_at':news_date} if fresh_report else None,
            'valuation_note':'This investigation contains newly assessed findings. Rebuild the Excel valuation separately using Update valuations; previous valuation numbers are not shown here.' if fresh_report else None,
            'evidence':evidence_summary(profile.id),
            'reported_results':reported, 'valuation_readiness':readiness,
            'news':news,'news_date':news_date, 'caveats':caveats,
            'investor_summary':'Focus on recurring earnings, cash generation and the assumptions needed to justify the market price. Use the valuation range to frame risk and further research, rather than treating one estimate as a trading signal.' if valuation else
            brief_data['investor_summary'] if reported and brief_data.get('investor_summary') else
            'A completed company valuation is not available yet. Reviewed company financials and appropriate assumptions are needed before drawing a valuation conclusion.'}
