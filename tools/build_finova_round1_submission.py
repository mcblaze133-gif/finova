"""A new two-page Round 1 submission design, independent of earlier templates."""
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/pdf/round1_submission/123_TrackC_Round1.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
for name, file in [('Finova', 'arial.ttf'), ('Finova-Bold', 'arialbd.ttf')]:
    pdfmetrics.registerFont(TTFont(name, 'C:/Windows/Fonts/' + file))
pdfmetrics.registerFontFamily('Finova', normal='Finova', bold='Finova-Bold', italic='Finova', boldItalic='Finova-Bold')
W, H = A4
X, RIGHT = 42, W - 42
CW = RIGHT - X
INK, BLUE, GREY = '#202B3A', '#2457C5', '#536170'
LIGHT, LINE, ORANGE = '#F2F5FA', '#DCE2EB', '#A54B20'
c = canvas.Canvas(str(OUT), pagesize=A4)
c.setTitle('Finova | Team 123 | Track C | Round 1 Solution Report')
c.setAuthor('Team 123')
c.setSubject('Working financial investigation prototype and post-Round 1 development plan')
styles = {
    'body': ParagraphStyle('body', fontName='Finova', fontSize=9.15, leading=12.55, textColor=colors.HexColor(INK)),
    'small': ParagraphStyle('small', fontName='Finova', fontSize=8.1, leading=10.8, textColor=colors.HexColor(GREY)),
    'label': ParagraphStyle('label', fontName='Finova-Bold', fontSize=9.1, leading=12.3, textColor=colors.HexColor(INK)),
}
y = H - 42


def text(value, width=CW, x=X, top=None, style='body'):
    global y
    top = y if top is None else top
    p = Paragraph(value, styles[style])
    _, height = p.wrap(width, H)
    if top - height < 46:
        raise ValueError(f'Page overflow: {value[:70]} at {top-height}')
    p.drawOn(c, x, top - height)
    return height


def body(value, gap=8, style='body'):
    global y
    y -= text(value, style=style) + gap


def section(title):
    global y
    y -= 5
    c.setFillColor(colors.HexColor(BLUE))
    c.setFont('Finova-Bold', 10.2)
    c.drawString(X, y - 10, title)
    y -= 21


def row(label, value, *, label_width=108, fill=False):
    global y
    p1, p2 = Paragraph(label, styles['label']), Paragraph(value, styles['body'])
    h = max(p1.wrap(label_width - 14, H)[1], p2.wrap(CW - label_width - 18, H)[1]) + 14
    if y - h < 46:
        raise ValueError('Table exceeds page: ' + label)
    if fill:
        c.setFillColor(colors.HexColor(LIGHT)); c.rect(X, y - h, CW, h, fill=1, stroke=0)
    p1.drawOn(c, X + 7, y - 7 - p1.height)
    p2.drawOn(c, X + label_width + 7, y - 7 - p2.height)
    c.setStrokeColor(colors.HexColor(LINE)); c.setLineWidth(.45)
    c.line(X, y - h, RIGHT, y - h)
    y -= h


def footer(page):
    c.setStrokeColor(colors.HexColor(LINE)); c.line(X, 35, RIGHT, 35)
    c.setFillColor(colors.HexColor(GREY)); c.setFont('Finova', 7.5)
    c.drawString(X, 23, 'TEAM 123   /   TRACK C   /   ROUND 1 SOLUTION REPORT')
    c.drawRightString(RIGHT, 23, f'{page} / 2')


# PAGE 1: proposition, end-to-end design, exact implementation boundary.
c.setFillColor(colors.HexColor(BLUE)); c.rect(X, H - 47, 28, 3, fill=1, stroke=0)
c.setFont('Finova-Bold', 9); c.drawString(X + 36, H - 48, 'FINANCIAL INVESTIGATION')
c.setFillColor(colors.HexColor(GREY)); c.setFont('Finova', 9); c.drawRightString(RIGHT, H - 48, 'TEAM 123  |  TRACK C')
c.setFillColor(colors.HexColor(INK)); c.setFont('Finova-Bold', 34); c.drawString(X, H - 91, 'Finova')
y = H - 107
body('From company disclosures to testable financial findings', style='label', gap=7)
body('A local research prototype with a ₹0 incremental budget. FMCG is the initial demonstration focus within the consumer/retail track.', style='small', gap=12)

section('01  The idea: investigate the relationship behind the headline')
body('Finova is a financial research investigator: it asks whether reported business progress is supported by operating economics. It connects filings, calls, peer context and new developments across time, then tests competing explanations. The intended discovery is a <b>tested financial relationship</b>, not a news summary. <b>Discovery comes first; valuation is a cross-check</b> that exposes the growth, margin and reinvestment assumptions needed to justify a range of values.')

section('02  Company name to an evidence-gated conclusion')
cards = [
    ('1  Investigate', 'Read company context.<br/>Choose hypotheses and<br/>competing explanations.'),
    ('2  Retrieve', 'Search prepared pages<br/>and fresh online leads.<br/>Read accessible originals.'),
    ('3  Test', 'Check figures and scope.<br/>Calculate in Excel.<br/>Search for contradictions.'),
    ('4  Deliver', 'Accept a supported finding<br/>or disclose the gap.<br/>Publish PDF + Excel.'),
]
gap = 9; width = (CW - gap * 3) / 4; height = 78
for i, (title, detail) in enumerate(cards):
    xx = X + i * (width + gap)
    c.setFillColor(colors.HexColor(LIGHT)); c.roundRect(xx, y - height, width, height, 5, fill=1, stroke=0)
    text(escape(title), width=width - 14, x=xx + 7, top=y - 9, style='label')
    text(detail, width=width - 14, x=xx + 7, top=y - 29, style='small')
y -= height + 11
body('The planner selects up to two hypotheses and alternatives from the company context: volume versus price/mix, margin sustainability, cash conversion or capital allocation. Supporting <b>and opposing</b> queries retrieve relevant local passages and accessible public originals. Annual reports, results, presentations and transcripts remain page-addressable in company evidence packs. Content hashes reuse unchanged extraction; each investigation attempts a fresh update check and creates new calculations and outputs.', gap=7)

section('03  Tools, models and public data')
row('Research & retrieval', 'Python 3.12 / FastAPI / SQLite; bounded planner, extractor, analyst and sceptical-reviewer roles. Gemini 3.1 Flash-Lite supplies structured research; Gemini 2.5 Flash-Lite with Google Search supports update discovery when available.', fill=True)
row('Evidence & access', 'Public company and exchange disclosures, user-supplied PDFs/CSVs, call transcripts and peer documents. Page-level text retrieval, archived PDF pages and screenshots; public RSS/search leads and permitted original-source fetching. Provider and access failures remain visible.')
row('Financial outputs', 'Formula-driven Excel with separate live bear/base/bull builds, method selection, sensitivities and assumptions. ReportLab produces the research PDF; a local web reader links claims to a compact source appendix. n8n workflows are optional adapters, not the website orchestrator.', fill=True)

section('04  What the working MVP demonstrates')
body('<b>HUL:</b> five annual periods, FY2022-FY2026, with 83 of 85 statement values populated from reviewed sources. The website generates an explanatory PDF and matching editable Excel. HUL uses conditional FCFF DCF and DDM; P/E and EV/EBITDA remain unvalidated multiple stress tests.', gap=6)
body('<b>Current boundary:</b> financial intake and company assumptions still require analyst review. Live source verification can be incomplete; no independently corroborated non-obvious discovery is claimed. Free allowances are capped and no paid fallback is enabled.', style='small', gap=0)
footer(1)
c.showPage()

# PAGE 2: evidence discipline, concrete hypothesis, deliverable and milestones.
y = H - 43
c.setFillColor(colors.HexColor(BLUE)); c.setFont('Finova-Bold', 9); c.drawString(X, y, 'RESEARCH STANDARD & NEXT MILESTONES')
c.setFillColor(colors.HexColor(INK)); c.setFont('Finova-Bold', 22); c.drawString(X, y - 34, 'A finding must survive challenge.')
y -= 52

section('05  Triangulation, contradiction and self-falsification')
row('Triangulate', 'Trace claims to original passages, pages, periods, units and accounting scope. Seek distinct origins: several company documents, copied coverage or model agreement do not establish independent corroboration. Search results remain leads until originals are read.', fill=True)
row('Challenge', 'Compare management promises with subsequent delivery, cash flows, peers and external evidence. Check reporting-scope changes, seasonality, acquisitions, exceptional items and restatements before calculating. The sceptical reviewer can weaken or reject a thesis; partial evidence remains partial.')
row('Falsify', 'State the strongest alternative and an observable outcome that would overturn the hypothesis. Confirmation needs a dated evidence trail and linked calculation. Missing contrary evidence is a gap, not proof.', fill=True)

section('06  A concrete research question, not a claimed discovery')
body('Reviewed HUL FY2026 versus FY2025 continuing-operation figures show revenue up <b>5.1%</b> and reconciled operating cash flow down <b>6.1%</b>.<super>1</super> Is growth less cash-generative, or is tax/working-capital timing responsible? Test the notes and subsequent disclosures. Recovery in comparable cash conversion, supported by a reconciled timing bridge, would weaken the adverse interpretation.', gap=6)
body('<super>1</super> HUL <link href="https://www.hul.co.in/files/annual-report-2025-26.pdf" color="#2457C5">FY2025-26 annual report</link>, printed pp. 368, 444; <link href="https://www.hul.co.in/files/hul-mq-26-results.pdf" color="#2457C5">FY2026 results</link>, PDF p. 8. Matched periods; continuing CFO = total CFO less signed discontinued CFO.', style='small', gap=7)

section('07  Generalisation and post-Round 1 plan to 25 October')
body('Shared prompts, schemas and business-model routing are designed for eligible NIFTY 50 companies within Track C. Methods depend on suitability and available evidence; missing inputs must exclude a method, not trigger invented facts. <b>Coverage without company-specific tuning is not yet demonstrated:</b> current financial cases include manual preparation. Test a held-out eligible company and an uncached same-sector company without changing prompts, then extend validation across consumer/retail business models.', gap=6)
row('21 Oct', 'Automate intake and research routing, with explicit exceptions; narrow evidence packs and parallelise independent source checks.', label_width=62, fill=True)
row('22 Oct', 'Broaden public-data reach and freshness; verify originals, financial reconciliations and matched-period peer comparisons.', label_width=62)
row('23 Oct', 'Test held-out/uncached companies for extraction accuracy, contradictions, formula recalculation, recovery and latency.', label_width=62, fill=True)
row('24 Oct', 'Improve investor-facing summaries and website usability; freeze a stable build, rehearse timing and verify backup/restore.', label_width=62)
row('25 Oct', 'Demonstrate a judge-selected eligible company live, defending the evidence trail, alternatives and falsification test.', label_width=62, fill=True)
y -= 8
body('These are planned milestones, not completed capabilities. Greater autonomy, wider coverage and faster runs must improve evidence quality as well as speed. The current prototype remains local and within verified free allowances; it makes no promise of exhaustive online coverage or error-free investment conclusions.', style='small', gap=0)
footer(2)
c.save()
reader = PdfReader(OUT)
assert len(reader.pages) == 2
all_text = '\n'.join(p.extract_text() or '' for p in reader.pages)
for required in ['Team', 'Finova', 'Triangulation', '25 Oct', '83 of 85', 'falsification', 'without company-specific tuning']:
    assert required.lower() in all_text.lower(), required
print(OUT)
