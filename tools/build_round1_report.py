"""Build the short, explicitly status-labelled competition solution report."""
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output' / 'pdf' / '123_TrackC_Round1.pdf'
OUT.parent.mkdir(parents=True, exist_ok=True)
navy = colors.HexColor('#142C43')
teal = colors.HexColor('#087E83')
body = ParagraphStyle('Body', fontName='Helvetica', fontSize=9.1, leading=12.1,
                      textColor=navy, spaceAfter=5)
head = ParagraphStyle('Head', parent=body, fontName='Helvetica-Bold', fontSize=10,
                      leading=13, textColor=teal, spaceBefore=5, spaceAfter=3)
small = ParagraphStyle('Small', parent=body, fontSize=8.2, leading=10.7, spaceAfter=0)
story = []

def p(text, style=body):
    story.append(Paragraph(text, style))

def section(title, text):
    p(title, head)
    p(text)

p('Finova', ParagraphStyle('Title', parent=body, fontName='Helvetica-Bold',
                            fontSize=27, leading=30, spaceAfter=3))
p('TRACK C  |  FINANCIAL INVESTIGATION  |  ROUND 1 SOLUTION REPORT',
  ParagraphStyle('Kicker', parent=small, textColor=teal, fontName='Helvetica-Bold', spaceAfter=6))
p('<b>Team 123</b> | Mohit Chaudhary &amp; Aum Bawiskar | 19 October 2026 | INR 0 incremental budget', small)
story.append(Spacer(1, 7))

section('The idea: discover a financial relationship, then try to disprove it',
    'Finova investigates whether reported business progress is supported by operating economics. '
    'Instead of summarising annual reports, it links disclosures across periods, tests competing explanations '
    'and quantifies a relationship. For example: does profit growth survive removal of a disclosed tax benefit, '
    'and does cash conversion support the remaining growth? This is an investigation template, not a claimed discovery. '
    'Valuation is a conditional appendix that shows what assumptions would justify a range of values.')

section('Company to evidence to discovery',
    '<b>Company input -&gt; business classification -&gt; initial evidence -&gt; up to two hypotheses and alternatives '
    '-&gt; targeted research plan -&gt; source retrieval and numerical checks -&gt; counterevidence review -&gt; discovery or insufficient evidence.</b> '
    'Questions adapt to the business: volume versus price/mix, margin sustainability, working capital, or store expansion. '
    'New disclosures and commodity, regulatory or geopolitical developments create investigation leads; '
    'they affect forecasts only after the exposure and evidence are reviewed.')

section('Tools, models and data',
    'The website starts a Python 3.12/FastAPI investigation backed by SQLite; n8n supplies optional adapters. A bounded Python state machine '
    'implements planner, extractor, analyst and sceptical-reviewer roles using Gemini with validated JSON responses. '
    'Original annual reports, exchange/company disclosures, presentations, call transcripts and CSVs are retained. '
    'PDF text/page retrieval and content-hash caches create reusable company evidence packs, including selected PDF pages '
    'and screenshots. Hypothesis-directed local and public search retrieves original sources where permitted; RSS supplies unverified update leads. '
    'Editable Excel formulas power visible bear/base/bull forecasts, sensitivities and valuation outputs. '
    'Free-tier call limits are enforced; no paid fallback is enabled.')

section('Triangulation, contradictions and self-falsification',
    'Claims must link to original passages, dates, units and accounting scope. The reviewer checks restatements, '
    'seasonality, acquisitions, exceptional items and conflicting management commentary. Multiple company documents '
    'count as one origin; another AI agreeing is not independent evidence. Supporting and opposing queries search local evidence, peer context and public originals. Distinct-origin and identical-content checks gate admission; ownership and syndication still need review. Each finding states its strongest '
    'counterargument and an observable future metric or disclosure that would weaken it. Unsupported claims are '
    'rejected or labelled partial. News headlines cannot become verified facts or numerical forecast adjustments.')

section('Track coverage without company-specific tuning',
    'The target is the eligible NIFTY 50 consumer/FMCG/retail universe within Track C, subject to the organiser\'s scope. '
    'Shared prompts and schemas route by business model and available evidence, not company-specific rules. '
    'DCF, trading multiples and conditional methods are selected by suitability and input quality. '
    'Missing inputs exclude a method rather than trigger invented assumptions. Five company valuation cases are prepared; '
    'manual case preparation does not yet prove generality. A held-out eligible company and an uncached same-sector '
    'company must pass before we claim autonomous coverage.')

section('Output: discovery first, valuation second',
    '<b>Company + evidence cutoff | discovery sentence | 3-5 significance points | dated timeline | '
    'sourced calculations | supporting/opposing links | strongest counterargument | falsification condition | '
    'evidence strength and reasons.</b> A results dashboard and downloadable Excel appendix show applicable '
    'valuations, scenario ranges, sensitivities and an assumption audit. Sources remain inspectable; internal logs '
    'stay outside the main report. Outputs explain implications without issuing an investment recommendation.')

section('What exists, and the build plan to 25 October',
    '<b>Built:</b> website-triggered hypothesis testing, targeted retrieval, claim-linked sources, timeline, counterargument and evidence-strength checks; five Excel cases and online impact review. Over 100 offline engineering tests pass; this is not financial certification. '
    '<b>Still required:</b> demonstrated live discoveries, independent corroboration and novelty validation, normalised peer comparisons, '
    'broader extraction validation, generality tests and timed live rehearsals.')

schedule = [
    ['19 Oct', 'Review and submit this PDF; add an eligible-company MVP only if verified.'],
    ['20-21 Oct', 'Verify original external evidence; test counterarguments and peer comparability.'],
    ['22-23 Oct', 'Test held-out/uncached companies, arithmetic and assumptions; fix failures and freeze.'],
    ['24-25 Oct', 'Rehearse timed runs and backup restore; demonstrate the judges\' company live.'],
]
table = Table([[Paragraph(a, small), Paragraph(b, small)] for a, b in schedule],
              colWidths=[61, A4[0]-72-61])
table.setStyle(TableStyle([
    ('BACKGROUND', (0,0),(-1,-1), colors.HexColor('#EEF5F6')),
    ('VALIGN',(0,0),(-1,-1),'TOP'),
    ('LEFTPADDING',(0,0),(-1,-1),7), ('RIGHTPADDING',(0,0),(-1,-1),7),
    ('TOPPADDING',(0,0),(-1,-1),3), ('BOTTOMPADDING',(0,0),(-1,-1),3),
]))
story.append(table)

def footer(c, doc):
    c.setStrokeColor(teal)
    c.line(36, 29, A4[0]-36, 29)
    c.setFont('Helvetica',7)
    c.setFillColor(navy)
    c.drawString(36,18,'123 | Finova | Round 1 | Working prototype + proposed completion plan')
    c.drawRightString(A4[0]-36,18,str(doc.page))

SimpleDocTemplate(str(OUT), pagesize=A4, leftMargin=36, rightMargin=36,
                  topMargin=27, bottomMargin=38,
                  title='123 - Finova - Track C - Round 1',
                  author='123: Mohit Chaudhary and Aum Bawiskar').build(story, onFirstPage=footer, onLaterPages=footer)
print(OUT)
