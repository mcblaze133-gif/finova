"""Render a source-linked equity research PDF from one immutable run snapshot.

Valuations, forecasts and historical diagnostics are read from Excel. This file
formats and interprets those results; it does not implement valuation formulas.
"""
import argparse
import json
import math
from pathlib import Path
from datetime import datetime,timezone,timedelta
from collections import OrderedDict
from xml.sax.saxutils import escape,quoteattr
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Spacer,PageBreak,NextPageTemplate,LongTable,Table,TableStyle,KeepTogether
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.graphics.shapes import Drawing,Rect,String,Line,Circle
from pypdf import PdfReader

INK=colors.HexColor('#17334A');TEAL=colors.HexColor('#147D73');PALE=colors.HexColor('#EFF5F5');GREY=colors.HexColor('#536672');LINE=colors.HexColor('#D8E3E7')
WIDTH,HEIGHT=A4;MARGIN=48;CONTENT=WIDTH-2*MARGIN
FONT=Path('C:/Windows/Fonts')
for name,file in [('Research','arial.ttf'),('Research-Bold','arialbd.ttf'),('Research-Italic','ariali.ttf')]:pdfmetrics.registerFont(TTFont(name,str(FONT/file)))
pdfmetrics.registerFontFamily('Research',normal='Research',bold='Research-Bold',italic='Research-Italic',boldItalic='Research-Bold')
STYLES={
 'body':ParagraphStyle('Body',fontName='Research',fontSize=9.6,leading=14.2,textColor=INK,spaceAfter=9),
 'small':ParagraphStyle('Small',fontName='Research',fontSize=8.1,leading=11.6,textColor=GREY,spaceAfter=7),
 'cell':ParagraphStyle('Cell',fontName='Research',fontSize=8.2,leading=11.2,textColor=INK),
 'headcell':ParagraphStyle('HeadCell',fontName='Research-Bold',fontSize=8.1,leading=11.2,textColor=colors.white),
 'h1':ParagraphStyle('H1',fontName='Research-Bold',fontSize=21,leading=26,textColor=INK,spaceAfter=17,keepWithNext=True),
 'h2':ParagraphStyle('H2',fontName='Research-Bold',fontSize=12,leading=17,textColor=TEAL,spaceBefore=12,spaceAfter=8,keepWithNext=True),
 'cover':ParagraphStyle('Cover',fontName='Research-Bold',fontSize=34,leading=41,textColor=INK,spaceAfter=24),
 'kicker':ParagraphStyle('Kicker',fontName='Research-Bold',fontSize=11,leading=17,textColor=TEAL,spaceAfter=12),
}
def clean(s):return str(s or '').replace('\u2011','-').replace('\u2013','-').replace('\u2014',' - ')
def P(s,style='body'):return Paragraph(escape(clean(s)).replace('\n','<br/>'),STYLES[style])

def referenced_paragraph(text,numbers,style='body'):
    """Visible numeric references point to the evidence appendix, never raw HTML."""
    numbers=list(dict.fromkeys(numbers))
    if any(not isinstance(n,int) or isinstance(n,bool) or n<1 for n in numbers):
        raise ValueError('Evidence references must be positive integers.')
    numbers.sort()
    refs=', '.join(f'<link href="#reference-{n}" color="#147D73">{n}</link>' for n in numbers)
    suffix=f' <super size="7">{refs}</super>' if refs else ''
    return Paragraph(escape(clean(text)).replace('\n','<br/>')+suffix,STYLES[style])
def num(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def fmt(v,kind='amount'):
    if not num(v):return 'Not available'
    if kind=='pct':return f'{v:.1%}'
    if kind=='multiple':return f'{v:.2f}x'
    if kind=='price':return f'₹{v:,.2f}'
    if kind=='shares':return f'{v:,.0f}'
    if kind=='number':return f'{v:,.2f}'
    return f'{v:,.1f}'
def ist(value):
    if not value:return 'Not recorded'
    d=datetime.fromisoformat(value.replace('Z','+00:00'))
    if not d.tzinfo:d=d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone(timedelta(hours=5,minutes=30))).strftime('%d %b %Y, %I:%M %p IST')
def safe_url(url):return isinstance(url,str) and (url.startswith('https://') or url.startswith('http://127.0.0.1:8000/'))
def readable(s):return clean(s).replace('_',' ').strip().capitalize()

def cover_matches(company,texts):
    # Long legal names legitimately wrap over multiple lines on the cover.
    normal=lambda value:' '.join(value.split())
    return len(texts)>=2 and normal(company) in normal(texts[0]) and 'Contents' in texts[1]
def link(text,url,style='cell'):
    if url and url.startswith('/'):url='http://127.0.0.1:8000'+url
    if not safe_url(url):return P(text,style)
    return Paragraph(f'<link href={quoteattr(url)} color="#147D73">{escape(clean(text))}</link>',STYLES[style])
def table(rows,widths=None,padding=8):
    prepared=[]
    for i,row in enumerate(rows):prepared.append([v if isinstance(v,Paragraph) else P(v,'headcell' if i==0 else 'cell') for v in row])
    t=LongTable(prepared,colWidths=widths or [CONTENT/len(rows[0])]*len(rows[0]),repeatRows=1,hAlign='LEFT')
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),INK),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),padding),
        ('BOTTOMPADDING',(0,0),(-1,-1),padding),('LINEBELOW',(0,0),(-1,0),.6,INK),
        ('LINEBELOW',(0,1),(-1,-1),.35,LINE),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,PALE])]))
    return t

CHART_COLORS=[INK,TEAL,colors.HexColor('#B87941'),colors.HexColor('#7D6AA2')]

def trend_chart(labels,series,*,unit='₹ crore',pct=False,breaks=(),height=215):
    """Small-multiple friendly zero-based vector chart; missing values break lines.

    All numeric inputs are reported actuals or saved Excel formula values. A
    scope/period boundary suppresses connecting segments, not the underlying data.
    """
    if not isinstance(labels,(list,tuple)) or any(len(vs)!=len(labels) for _,vs in series):
        raise ValueError('Chart labels and saved-value series must align exactly.')
    d=Drawing(CONTENT,height);left=54;right=CONTENT-14;bottom=43;top=height-42
    values=[v for _,vs in series for v in vs if num(v)]
    if not values:
        d.add(String(0,height-30,'No numeric observations available; no trend inferred.',fontName='Research',fontSize=10,fillColor=GREY))
        return d
    lo=min([0]+values);hi=max([0]+values)
    if hi==lo:hi=lo+1
    pad=(hi-lo)*.12;hi+=pad
    if lo<0:lo-=pad
    y=lambda v:bottom+(v-lo)/(hi-lo)*(top-bottom)
    xs=[left+(right-left)*i/max(1,len(labels)-1) for i in range(len(labels))]
    d.add(String(left,height-10,unit,fontName='Research',fontSize=8,fillColor=GREY))
    for tick in range(4):
        v=lo+(hi-lo)*tick/3;yy=y(v)
        d.add(Line(left,yy,right,yy,strokeColor=LINE,strokeWidth=.5))
        text=f'{v:.0%}' if pct else f'{v:,.0f}'
        d.add(String(left-7,yy-3,text,fontName='Research',fontSize=7.5,textAnchor='end',fillColor=GREY))
    for i,label in enumerate(labels):
        d.add(String(xs[i],bottom-16,str(label),fontName='Research',fontSize=7.5,textAnchor='middle',fillColor=INK))
    for j,(name,vs) in enumerate(series):
        color=CHART_COLORS[j%len(CHART_COLORS)]
        lx=left+j*(CONTENT-left)/max(1,len(series))
        d.add(Line(lx,height-25,lx+14,height-25,strokeColor=color,strokeWidth=2))
        d.add(String(lx+19,height-28,name,fontName='Research',fontSize=8,fillColor=color))
        for i,v in enumerate(vs):
            if not num(v):continue
            if i and i not in breaks and num(vs[i-1]):d.add(Line(xs[i-1],y(vs[i-1]),xs[i],y(v),strokeColor=color,strokeWidth=2))
            d.add(Circle(xs[i],y(v),2.7,fillColor=color,strokeColor=colors.white,strokeWidth=.5))
    return d

def scope_breaks(periods):
    return [i for i in range(1,len(periods)) if periods[i]['scope']!=periods[i-1]['scope']
            or abs(periods[i]['duration_days']-periods[i-1]['duration_days'])>2
            or not 300<=periods[i]['duration_days']<=370 or not 300<=periods[i-1]['duration_days']<=370]

class Document(BaseDocTemplate):
    def afterFlowable(self,f):
        if isinstance(f,Paragraph) and getattr(f,'toc_key',None):
            self.canv.bookmarkPage(f.toc_key)
            self.canv.addOutlineEntry(f.getPlainText(),f.toc_key,0,False)
            self.notify('TOCEntry',(0,f.getPlainText(),self.page,f.toc_key))

def build(data,target):
    company=data['company'];raw=data['research'];history=data['history'];val=data.get('valuation') or {};story=[];sections=[]
    def section(title):
        if sections:story.append(PageBreak())
        h=P(title,'h1');h.toc_key='section-'+str(len(sections)+1);sections.append(title);story.append(h)
    def sub(title):story.append(P(title,'h2'))
    def body(text):story.append(P(text))
    def note(text):story.append(P(text,'small'))
    sources=OrderedDict()
    def source(key,title,url,page=None,quote=None):
        key=(url or key,str(page or ''))
        if key not in sources:sources[key]={'code':len(sources)+1,'title':title,'url':url,'pages':set(),'quotes':[]}
        if page:sources[key]['pages'].add(str(page))
        if quote and quote not in sources[key]['quotes']:sources[key]['quotes'].append(quote)
        return sources[key]['code']
    passages={p['id']:p for p in [*raw.get('passages',[]),*raw.get('section_analysis',{}).get('passage_catalog',[])]}
    def statement(item):
        if not item:return
        refs=[]
        for c in item.get('citations',[]):
            p=passages.get(c.get('passage_id'))
            if not p:continue
            url=f'http://127.0.0.1:8000/documents/{p["document_id"]}/original#page={p["pdf_page"]}'
            code=source(str(p['document_id']),p.get('title','Company disclosure'),url,p['pdf_page'],c.get('quote'))
            refs.append(code)
        story.append(referenced_paragraph(item.get('text',''),refs))
    def actual_cell(period,metric):
        v=period['values'].get(metric)
        text=fmt(v if metric=='shares' or not num(v) else v/10000000,'shares' if metric=='shares' else 'amount')
        refs=period.get('sources',{}).get(metric,[])
        if not refs:return P(text,'cell')
        r=refs[0];url=r.get('url');key=r.get('sha256') or r['file']
        source(key,Path(r['file']).name,'http://127.0.0.1:8000'+url if url else None,r.get('pages'))
        return link(text,url)
    targeted=data.get('targeted_research') or {}
    preview=data.get('preview',False)
    validation=data.get('validation_only',False)
    incomplete=raw.get('status')!='completed' or (data.get('news') or {}).get('status')!='assessed' or data.get('coverage',{}).get('complete') is False
    story.extend([Spacer(1,70),P('FINOVA  /  EQUITY RESEARCH','kicker'),Spacer(1,42),P(company,'cover'),
        P('Financial analysis and valuation','h1'),P('Indian FMCG and consumer products','kicker'),Spacer(1,38),
        P(('VALIDATION REPORT - AI ASSESSMENT NOT RUN' if validation else 'LAYOUT PREVIEW - EXISTING DATED RESEARCH' if preview else 'PRELIMINARY RESEARCH - COVERAGE INCOMPLETE' if incomplete else 'COMPANY RESEARCH REPORT'),'kicker'),
        P('Prepared '+ist(data['generated_at'])),P('Team 123','small'),Spacer(1,38),
        P('Historical statements, operating evidence, scenario valuation and the conditions needed to support an investment view.','body'),
        P('Valuation estimates depend on explicitly labelled analyst assumptions. Material reporting-scope differences and evidence gaps are disclosed.','small'),NextPageTemplate('Body'),PageBreak(),P('Contents','h1')])
    toc=TableOfContents();toc.levelStyles=[ParagraphStyle('ContentsEntry',fontName='Research',fontSize=10,leading=17,textColor=INK,spaceBefore=7,leftIndent=0,firstLineIndent=0,rightIndent=22)]
    story.extend([toc,PageBreak()])

    section('01  Investment perspective')
    body('This report combines reported financial history, a company-specific evidence review and scenario valuations calculated in the accompanying Excel model.')
    if preview:body('This is a layout preview assembled from existing dated inputs. It is not a newly completed online investigation.')
    if validation:body('This is a workflow validation run: source packs were reread, free public retrieval was attempted and a new Excel model was built. Generative AI was deliberately not called. Operating interpretations and news impacts have not received a fresh AI assessment; this PDF is not a completed investment investigation.')
    body('Research started '+ist(data['started_at'])+'. Report prepared '+ist(data['generated_at'])+'.')
    if data.get('revision_note'):note(data['revision_note'])
    if raw.get('discovery'):sub('Principal finding');statement(raw['discovery'])
    else:
        sub('Current research conclusion')
        body('The available review has not established a sufficiently corroborated non-obvious discovery. Financial observations and conditional valuations below remain useful for research, but do not establish an investment thesis on their own.')
    weighted=val.get('weighted')
    if weighted:
        story.append(table([['Conditional value per share','Bear','Base','Bull'],['Selected-method reconciliation',*[fmt(weighted[k],'price') for k in ('bear','base','bull')]]],[190,103,103,CONTENT-396]))
    body(val.get('summary','No completed company valuation is available for this report.'))
    note('Market reference '+fmt(val.get('market_price'),'price')+' dated '+str(val.get('market_price_date') or 'unavailable')+'. This is a dated observation, not a live quote.')
    observations=history.get('excel_diagnostics',[]);hp=history.get('periods',[])
    if len(observations)>1 and hp[-1]['scope']==hp[-2]['scope'] and abs(hp[-1]['duration_days']-hp[-2]['duration_days'])<=2:
        a,b=observations[-2],observations[-1]
        sub('Financial scorecard')
        rows=[['Indicator',hp[-2]['label'],hp[-1]['label'],'Investor interpretation']]
        for label,key,kind,meaning in [('Revenue growth','revenue_growth','pct','Test volume versus price/mix and acquisitions.'),
            ('Operating EBITDA margin','ebitda_margin','pct','Profit per rupee of sales; test durability of the cost/mix bridge.'),
            ('CFO / parent profit','cash_conversion','multiple','Cash backing of profit; test working-capital timing.'),
            ('Cash after capex, ₹ cr','cash_after_capex_crore','amount','Reinvestment-adjusted cash diagnostic; not distributable cash.')]:
            rows.append([label,fmt(a.get(key),kind),fmt(b.get(key),kind),meaning])
        story.append(table(rows,[122,66,66,CONTENT-254]))
        note('Sources and definitions: Sections 3-4 and the Excel Statement history schedule. These are reported-data observations, separate from a corroborated research discovery.')
    if incomplete:body('Coverage remains incomplete. A failed or unverified news check does not establish that no company developments occurred. No missing evidence has been treated as a positive conclusion.')
    sub('Added analytical value - and its limits')
    body('The useful addition to a company presentation is the cross-check: reported profit against cash, cash after capex against reinvestment, operating history against forecast assumptions, and each hypothesis against a contrary explanation. Sources and editable scenarios make these checks reproducible. This report does not establish that a finding is original relative to all sell-side or AI research.')

    sector=raw.get('sector_sections',[])
    section('02  Business, operating drivers and industry evidence')
    supported=[s for s in sector if s.get('topic') not in ('Risks and catalysts','Capital allocation')]
    if not supported:body('The current review did not establish enough cited operating evidence to write a company-specific business, competitive-position or management assessment. These areas remain open research questions rather than assumed strengths or weaknesses.')
    interpretations={
      'Business and products':'Portfolio breadth matters through the economics of each category: repeat purchase, brand investment, distribution reach and the price a customer is willing to pay. A broad portfolio can spread distribution costs, but it can also conceal weak categories within group growth. Assess the disclosed businesses separately before assigning one growth rate or valuation premium to the whole company.',
      'Demand, volume and pricing':'Sales growth can come from more units, higher prices, a richer product mix or acquisitions. Those sources have different implications for repeatable growth. Volume supported by distribution and repeat purchase provides a different forecast foundation from a price increase that merely offsets input inflation. Rural and urban commentary should be tested against dated, comparable volume disclosures rather than treated as a quantified demand split.',
      'Costs and profitability':'Operating margin measures how much sales remain after operating costs. Changes can reflect input prices, price increases, product mix, advertising or operating efficiency. The margin chart shows the financial outcome; it does not establish which driver caused it. Forecasts should test whether the improvement survives normal commodity costs and adequate brand investment, and whether any related-party pricing disclosure applies only to specified transactions.',
      'Segments and geography':'Group averages can conceal different growth rates, capital needs and margin profiles across categories and regions. Segment information helps test whether group growth is broad-based or concentrated in one business. A geographic description alone does not establish geographic revenue exposure; quantified regional forecasts require the corresponding disclosures.',
      'Competition and economic moat':'Brand recognition and distribution are possible sources of competitive advantage, but their economic value depends on pricing power, repeat demand and returns after reinvestment. Management market-share statements remain attributed claims until independently checked. A valuation premium needs evidence that these advantages protect profitable growth, rather than merely demonstrating the size of the business.',
      'Management and governance':'Disclosed controls and board processes explain how decisions are overseen. They do not, by themselves, prove that acquisitions are attractive, related-party prices are optimal or risks cannot materialise. Compare stated priorities with subsequent delivery and capital allocation. Equally, the existence of a risk-control policy is not evidence that a conflict or governance failure has occurred.',
      'Macro and commodity exposure':'Commodity, packaging, freight and currency changes can affect margins before pricing or sourcing responses take effect. The investor question is the timing and size of the company-specific exposure, including hedges and the ability to pass costs through. An industry-wide shock should therefore become a scenario to investigate; it should not become an automatic numerical forecast change without verified exposure.'}
    margin_chart_shown=False
    for s in supported:
        topic_start=len(story)
        sub(s['topic'])
        for item in s['statements']:statement(item)
        if s['topic']=='Costs and profitability' and hp and observations:
            story.append(trend_chart([p['end'][:4] for p in hp],[('Operating EBITDA margin',[d.get('ebitda_margin') for d in observations]),('Parent net margin',[d.get('net_margin') for d in observations])],unit='Reported margin, %',pct=True,breaks=scope_breaks(hp)))
            refs=[]
            for period in hp:
                for metric in ('revenue','ebitda','net_income'):
                    for r in period.get('sources',{}).get(metric,[])[:1]:
                        refs.append(source(r['file'],Path(r['file']).name,'http://127.0.0.1:8000'+r['url'] if r.get('url') else None,r.get('pages')))
            story.append(referenced_paragraph('Annual margins from the matching Excel statement schedule. The gap in the lines marks a change in reporting scope; it is not a missing year.',refs,'small'))
            if len(hp)>1 and len(observations)==len(hp) and hp[-2]['scope']==hp[-1]['scope'] and abs(hp[-2]['duration_days']-hp[-1]['duration_days'])<=2:
                a,b=observations[-2:]
                if all(num(d.get(k)) for d in (a,b) for k in ('ebitda_margin','net_margin')):
                    body('For '+hp[-1]['label']+', operating EBITDA margin was '+fmt(b['ebitda_margin'],'pct')+' compared with '+fmt(a['ebitda_margin'],'pct')+' in the preceding comparable period. Parent net margin was '+fmt(b['net_margin'],'pct')+' versus '+fmt(a['net_margin'],'pct')+'. Read these together: operating margin describes the trading outcome, while net margin also reflects financing, tax, non-operating items and minority attribution. A margin change alone does not establish pricing power or operating efficiency.')
            margin_chart_shown=True
        body(interpretations.get(s['topic'],''))
        body(s['investor_use'])
        if s.get('counterevidence'):
            statement({'text':'Counterpoint. '+s['counterevidence']['text'],'citations':s['counterevidence'].get('citations',[])})
        if s.get('gaps'):note('What remains unresolved: '+'; '.join(clean(g).rstrip(' .;') for g in s['gaps'])+'.')
        if s['topic']=='Costs and profitability':story[topic_start:]=[KeepTogether(story[topic_start:])]
    if not supported:
        sub('FMCG operating questions')
        story.append(table([['Driver','Financial relationship to investigate'],
            ['Demand and distribution','Separate volume-led sales growth from price/mix. Test rural/urban demand, distribution additions and channel shifts against disclosed evidence.'],
            ['Pricing and input costs','Compare pricing actions with raw-material and packaging pressure. Margin improvement alone does not identify the cause.'],
            ['Brand and category economics','Test category mix, brand investment and competitive intensity. A premium multiple requires evidence of durable returns and growth.']], [125,CONTENT-125]))
        note('These are analytical questions, not findings about an unverified company exposure.')

    section('03  Historical financial performance')
    note(history.get('qualification',''))
    periods=history.get('periods',[])
    headers=['₹ crore unless stated']+[p['label']+'\n'+p['scope']+'\n'+str(p['duration_days'])+' days' for p in periods]
    if periods:
        labels=[str(p['end'])[:4]+('*' if p['duration_days']>400 else '') for p in periods];breaks=scope_breaks(periods)
        actual=lambda metric:[p['values'].get(metric)/10000000 if num(p['values'].get(metric)) else None for p in periods]
        sub('Sales scale and operating earnings')
        story.append(trend_chart(labels,[('Revenue',actual('revenue'))],breaks=breaks))
        story.append(trend_chart(labels,[('Operating EBITDA',actual('ebitda')),('Parent profit',actual('net_income'))],breaks=breaks))
        note('Source: linked reported statements below. Labels show the period-end year. '+('* marks a period longer than 400 days. ' if any(p['duration_days']>400 for p in periods) else '')+'Separate panels preserve the earnings scale. Lines stop at changes in reporting scope or period length; points remain as reported, without annualisation.')
        body('Read sales growth alongside earnings: rising revenue creates value only if operating economics and reinvestment produce sustainable cash returns. These charts establish reported trends; attribution to volume, pricing or acquisitions requires the operating evidence review.')
        widths=[145]+[(CONTENT-145)/len(periods)]*len(periods)
        for title,metrics in [('Revenue and profitability',['revenue','ebitda','ebit','net_income']),('Cash generation and reinvestment',['cfo','capex','dividends']),('Balance sheet and capital',['assets','liabilities','book_equity','nci','debt','cash','operating_nwc','shares'])]:
            sub(title);rows=[headers]
            metric_labels={m['id']:m['label'] for m in history['metrics']}
            for m in metrics:
                if any(m in p['values'] for p in periods):rows.append([metric_labels[m]]+[actual_cell(p,m) for p in periods])
            story.append(table(rows,widths,padding=5));story.append(Spacer(1,10))
        note('Click a reported figure to open its archived original PDF page. Sources are also listed in Appendix A. A blank/unavailable figure is not zero. Closing shares are actual counts; split/bonus adjustments must be reconciled before historical per-share comparisons.')
        if len({p['scope'] for p in periods})>1:body('Reporting scope changes within this series. Total operations before a demerger and subsequent continuing operations are shown separately. No uninterrupted like-for-like growth trend is claimed across that boundary.')
        for p in periods:
            if p['duration_days']>400:body(p['label']+' spans '+str(p['duration_days'])+' days. It has not been annualised or treated as a comparable twelve-month year.')

    section('04  Earnings quality, liquidity and capital allocation')
    diagnostics=history.get('excel_diagnostics',[])
    if periods and diagnostics:
        sub('Profitability and cash: the checks that matter together')
        if not margin_chart_shown:story.append(trend_chart(labels,[('EBITDA margin',[d.get('ebitda_margin') for d in diagnostics]),('Net margin',[d.get('net_margin') for d in diagnostics])],unit='Reported margin, %',pct=True,breaks=breaks))
        story.append(trend_chart(labels,[('Operating cash flow',actual('cfo')),('Parent profit',actual('net_income'))],breaks=breaks))
        note('Sources: Excel Statement history rows 29-30 and 33; reported CFO and parent profit. CFO is group cash flow, whereas profit is attributable to the parent: this is a diagnostic, not an ownership-matched conversion ratio.')
        story.append(trend_chart(labels,[('Capital expenditure',actual('capex')),('Cash after capex',[d.get('cash_after_capex_crore') for d in diagnostics])],breaks=breaks))
        note('Cash after capex is the saved Excel CFO-less-capex result, not FCFF. Declining capex can improve this measure even when earnings convert less strongly into operating cash.')
    if periods:
        rows=[['Excel diagnostic']+[p['label'] for p in periods]]
        for label,key,kind in [('Operating EBITDA margin','ebitda_margin','pct'),('Attributable net margin','net_margin','pct'),('Operating cash flow / parent PAT','cash_conversion','multiple'),('Operating cash flow less capex, ₹ cr','cash_after_capex_crore','amount')]:
            if any(num(d.get(key)) for d in diagnostics):rows.append([label]+[fmt(d.get(key),kind) for d in diagnostics])
        story.append(table(rows,[155]+[(CONTENT-155)/len(periods)]*len(periods)))
    if len(diagnostics)>1:
        a,b=diagnostics[-2],diagnostics[-1]
        if periods[-2]['scope']==periods[-1]['scope'] and abs(periods[-2]['duration_days']-periods[-1]['duration_days'])<=2 and all(num(d.get(k)) for d in (a,b) for k in ('cash_conversion','cash_after_capex_crore')) and b['cash_conversion']<a['cash_conversion'] and b['cash_after_capex_crore']>a['cash_after_capex_crore']:
            body('A useful distinction in the latest year: cash remaining after capex increased from ₹'+fmt(a['cash_after_capex_crore'])+' crore to ₹'+fmt(b['cash_after_capex_crore'])+' crore while cash conversion weakened. Better post-capex cash does not therefore establish stronger cash backing for earnings. Reconcile operating working capital and the timing/adequacy of capital spending before extrapolating the improvement.')
    body('Net margin shows how much reported revenue reaches parent shareholders as profit. Compare exceptional items, tax, minority interests and scope before interpreting a change as better underlying economics.')
    body('Cash conversion compares operating cash flow with parent-attributable profit. A weak ratio can prompt work on receivables, inventories, payables and non-cash earnings. A strong ratio can reflect temporary working-capital release. Group cash flow and parent profit are not identical ownership measures.')
    body('Operating cash flow less capital expenditure shows historical cash remaining after the stated capital spending. It is not FCFF, distributable cash or a dividend forecast. Acquisitions, debt service, lease accounting and other cash claims require separate consideration.')
    body('Read debt and cash alongside the minority-interest and lease definitions. Compare dividends with recurring cash generation and reinvestment needs rather than assuming that past payouts establish a sustainable policy.')
    for s in sector:
        if s['topic']=='Capital allocation':
            sub(s['topic'])
            for item in s['statements']:statement(item)
            body('Investor use: '+s['investor_use'])
            if s.get('counterevidence'):
                sub('Counterevidence / alternative');statement(s['counterevidence'])
            if s.get('gaps'):note('Remaining evidence: '+'; '.join(s['gaps']))
    note('Diagnostic figures above are linked to the Statement history schedule in the accompanying Excel workbook. Missing or non-comparable inputs do not produce a ratio.')

    section('05  Current developments and macro exposure')
    news=data.get('news') or {};nr=news.get('result') or {}
    body('Online check recorded '+ist(news.get('checked_at'))+'.')
    events=nr.get('events',[]);news_sources={s['source_id']:s for s in nr.get('sources',[])}
    if not events:body('No completed, source-assessed development is available from this check. This is a coverage gap, not evidence that the company has no new announcements or market risks.')
    for e in events:
        sub(e['headline']);body('Evidence status: '+readable(e.get('fact_status','Unverified'))+'. '+e.get('mechanism',''))
        body('Potential model implications: '+', '.join(readable(d) for d in e.get('active_model_inputs',e.get('drivers_to_review',[])))+'. '+e.get('review_action','Verify exposure before changing assumptions.'))
        if e.get('falsification'):body('What would change this assessment: '+e['falsification'])
        refs=[]
        for sid in e.get('source_ids',[]):
            s=news_sources.get(sid)
            if s:
                code=source(s.get('url',str(sid)),s.get('title','External source'),s.get('url'))
                refs.append(code)
        if refs:story.append(referenced_paragraph('Evidence for this development.',refs,'small'))
    body('For FMCG, inflation, household income, commodity and packaging costs, currency and supply disruptions can affect demand, gross margins and cash needs. An event is financially relevant only after the company exposure, timing and ability to pass costs through are established.')
    note('News does not automatically change numerical assumptions. The report distinguishes possible transmission channels from verified financial effects; quantified changes require sourced inputs or an explicit analyst estimate.')
    leads=nr.get('news_leads',[])
    if leads:
        sub('Unassessed leads - excluded from conclusions')
        for lead in leads[:8]:story.append(link(lead.get('headline','News lead')+' ('+str(lead.get('published_at','date unavailable'))+')',lead.get('url'),'small'))
    if news.get('status')!='assessed':body('The current news review is incomplete or contains unverified sources. Recent-event coverage does not support an unqualified final conclusion.')

    section('06  Valuation overview and triangulation')
    body('Each method uses the company-specific assumptions and reporting basis shown in the Excel model. Methods with insufficient inputs or unsuitable economics are excluded; their reasons appear in Appendix C.')
    rows=[['Method','Bear / share','Base / share','Bull / share','Treatment']]
    for m in val.get('methods',[]):rows.append([m['method'],*[fmt(m[k],'price') for k in ('bear','base','bull')],'Primary' if m.get('primary') else 'Cross-check / stress'])
    if len(rows)>1:story.append(table(rows,[140,83,83,83,CONTENT-389]))
    if weighted and all(num(v) and v>0 for v in weighted.values()):
        chart=Drawing(CONTENT,175);maximum=max([*weighted.values()]+([val['market_price']] if num(val.get('market_price')) else []))*1.15
        chart.add(Line(35,35,CONTENT-12,35,strokeColor=LINE))
        for i,(case,color) in enumerate([('bear','#AD7969'),('base','#17334A'),('bull','#147D73')]):
            value=weighted[case];x=85+i*137;height=value/maximum*110
            chart.add(Rect(x,35,65,height,fillColor=colors.HexColor(color),strokeColor=None))
            chart.add(String(x+32.5,18,case.title(),fontName='Research',fontSize=9,textAnchor='middle',fillColor=INK))
            chart.add(String(x+32.5,41+height,fmt(value,'price'),fontName='Research-Bold',fontSize=9,textAnchor='middle',fillColor=INK))
        if num(val.get('market_price')):
            y=35+val['market_price']/maximum*110
            chart.add(Line(35,y,CONTENT-12,y,strokeColor=GREY,strokeDashArray=[3,3]))
            chart.add(String(CONTENT-12,160,'Dated market reference '+fmt(val['market_price'],'price'),fontName='Research',fontSize=8,textAnchor='end',fillColor=GREY))
        story.extend([Spacer(1,12),chart]);note('Conditional scenario values. Market reference dated '+str(val.get('market_price_date'))+'. Source: Excel Dashboard D25:F25 and Market D7.')
    body('DCF discounts forecast free cash flow to the firm and reconciles enterprise value to equity after debt, cash, minorities and other claims. It is sensitive to operating forecasts, the discount rate and terminal reinvestment.')
    if data['forecasts']['Base'].get('dcf_bridge'):
        sub('DCF enterprise-to-equity reconciliation')
        rows=[['₹ crore - Excel saved results','Bear','Base','Bull']]
        for label in data['forecasts']['Base']['dcf_bridge']:
            rows.append([label]+[fmt(data['forecasts'][case]['dcf_bridge'].get(label)/10000000) if num(data['forecasts'][case]['dcf_bridge'].get(label)) else 'Not available' for case in ('Bear','Base','Bull')])
        story.append(table(rows,[190]+[(CONTENT-190)/3]*3))
        note('Source: scenario E54, E61, E66, F66 and E84:E85. Interim cash accrual and distribution timing are estimates rolling the reported balance forward; they are not a newly reported interim balance sheet. EV plus the equity adjustment equals equity value; other rows explain assumptions, not additional amounts to add.')
        implied=data['forecasts']['Base'].get('market_implied',{})
        if implied:
            sub('Expectations embedded in the dated market reference')
            story.append(table([['Forward P/E','Forward EV/EBITDA','EPS at selected P/E'],
                [fmt(implied.get('P/E'),'multiple'),fmt(implied.get('EV/EBITDA'),'multiple'),fmt(implied.get('EPS at selected P/E'),'price')]]))
            note('Source: Base N19:N21. These use the model forecast and dated share price; they are not an independently retrieved peer comparison or a solved market-implied growth/margin forecast.')
    if any(m['method']=='DDM' for m in val.get('methods',[])):body('DDM values expected shareholder distributions using cost of equity. A credible payout policy and sustainable terminal returns are necessary; a high historical dividend does not on its own validate the model.')
    if any(m['method']=='SOTP' for m in val.get('methods',[])):body('SOTP values economically distinct businesses separately, then reconciles ownership and unallocated claims. Segment multiples remain assumptions where comparable market evidence is incomplete.')
    body('P/E and EV/EBITDA outputs marked as stress tests show what selected earnings or operating-profit multiples imply. They are not independently validated comparable-company conclusions when a reviewed category-matched forward peer set is absent.')
    if weighted:
        sub('Reconciled conditional range')
        body('Bear '+fmt(weighted['bear'],'price')+'; base '+fmt(weighted['base'],'price')+'; bull '+fmt(weighted['bull'],'price')+' per share. Weights reflect the selected methods, not a mechanical average of every available formula.')
    for m in data['methods']:
        if m.get('weight'):body(m['method']+': '+fmt(m['weight'],'pct')+' weight. '+str(m.get('weight_rationale') or 'Weight rationale requires review.'))
    story.append(link('Open the accompanying editable Excel valuation',data['workbook_url'],'small'))
    note('Valuation date: '+str(val.get('valuation_date') or 'not available')+'. Native desktop Excel recalculation has not been independently verified. Calculation-engine checks and saved formula values were used for this PDF.')

    section('07  Forecasts, assumptions and scenario analysis')
    body('Bear, base and bull are weaker, central and stronger operating/valuation scenarios. They are not probabilities, guaranteed price bounds or different reporting histories. All three remain visible, independently editable builds in Excel.')
    for metric in ('Revenue','FCFF'):
        series=[(name,[v/10000000 if num(v) else None for v in data['forecasts'][name]['rows'][metric]]) for name in ('Bear','Base','Bull')]
        sub(metric+' - three operating scenarios')
        story.append(trend_chart([str(p)[:4] for p in data['forecasts']['Base']['periods']],series))
        note('Source: the three visible Excel forecast builds. These are conditional scenarios, not a probability band. FCFF includes tax, working capital and reinvestment, so it can diverge from sales.')
    for name,forecast in data['forecasts'].items():
        sub(name+' scenario')
        headers=['₹ crore except EPS']+[str(p or 'Period missing') for p in forecast['periods']]
        rows=[headers]
        for label,values in forecast['rows'].items():rows.append([label]+[fmt(v if label=='EPS' or not num(v) else v/10000000,'price' if label=='EPS' else 'amount') for v in values])
        if any(num(v) for v in forecast.get('ebitda_margin',[])):rows.append(['EBITDA margin']+[fmt(v,'pct') for v in forecast['ebitda_margin']])
        story.append(table(rows,[130]+[(CONTENT-130)/5]*5))
        note('WACC '+fmt(forecast.get('wacc'),'pct')+'; cost of equity '+fmt(forecast.get('cost_equity'),'pct')+'; terminal growth '+fmt(forecast.get('terminal_growth'),'pct')+'. These are estimates, not historical facts.')
    dependence=data['forecasts']['Base'].get('terminal_dependence')
    grid=data['forecasts']['Base'].get('sensitivity',{})
    if grid and all(num(v) for row in grid.get('values',[]) for v in row):
        sub('Base DCF sensitivity - value per share')
        rows=[['Terminal g / WACC']+[fmt(v,'pct') for v in grid['wacc']]]
        rows.extend([[fmt(g,'pct')]+[fmt(v,'price') for v in vs] for g,vs in zip(grid['growth'],grid['values'])])
        heatmap=table(rows,[105]+[(CONTENT-105)/5]*5)
        minimum=min(v for row in grid['values'] for v in row);maximum=max(v for row in grid['values'] for v in row)
        for y,vs in enumerate(grid['values'],1):
            for x,v in enumerate(vs,1):
                shade=(v-minimum)/(maximum-minimum) if maximum>minimum else .5
                heatmap.setStyle(TableStyle([('BACKGROUND',(x,y),(x,y),colors.Color(.95-.30*shade,.98-.13*shade,.98-.17*shade))]))
        heatmap.setStyle(TableStyle([('BOX',(3,3),(3,3),1.3,TEAL)]))
        story.append(heatmap)
        note('Source: Base K8:P13 saved native Data Table values. WACC varies across columns; terminal growth varies down rows. This is a conditional valuation stress, not a forecast-probability distribution.')
    if num(dependence):body('Base DCF terminal value represents '+fmt(dependence,'pct')+' of enterprise value. A large contribution concentrates the conclusion in long-run growth, returns and capital-cost assumptions. Review the live WACC / terminal-growth sensitivity tables in Excel.')
    body('Changing an assumption can change the value without any change in reported history. Revenue growth should be tested against volume and price/mix evidence; margin changes against input costs, mix, advertising and operating leverage. Forecast cash flow also depends on tax, working capital and reinvestment.')
    note('The complete driver values, source dates, source categories, confidence and rationale are retained in the Excel Assumptions sheet. Appendix B summarises the principal valuation inputs used here. This report does not infer a new numerical assumption from an unverified headline.')

    section('08  Discovery, counterevidence and falsification')
    if targeted.get('signals'):
        sub('Financial relationships requiring explanation')
        for signal in targeted['signals']:
            sub(signal['title']);body(signal['observation'])
            story.append(table([['How an investor can use it','Strongest alternative / disconfirming test'],
                [signal['investor_use'],signal['alternative']+'\n\n'+signal['falsification']]],[CONTENT*.46,CONTENT*.54]))
            note(signal['status']+'. Numbers: historical tables and charts in Sections 3-4; targeted original passages and unresolved evidence in Appendix D.')
    if raw.get('discovery'):sub('Supported candidate');statement(raw['discovery'])
    elif raw.get('candidate_discovery'):sub('Hypothesis requiring corroboration');statement(raw['candidate_discovery'])
    else:body('A defensible discovery was not established in this run. The absence of a finding is not proof that the business has no risks or opportunities.')
    if raw.get('significance'):
        sub('Why it matters')
        for s in raw['significance']:statement(s)
    if raw.get('timeline'):
        sub('Dated evidence timeline')
        for t in raw['timeline']:body(str(t['date']));statement(t)
    if raw.get('counterargument'):sub('Strongest counterargument');statement(raw['counterargument'])
    if raw.get('falsification_condition'):sub('What would invalidate the thesis');body(raw['falsification_condition'])
    strength=raw.get('evidence_strength') or {}
    note('Evidence strength: '+str(strength.get('rating','Weak / not established'))+'. '+' '.join(strength.get('reasons',[])[:6])+'. Multiple company documents do not establish independent corroboration or a non-obvious causal discovery.')

    section('09  Investment risks, catalysts and monitoring')
    risks=[s for s in sector if s['topic']=='Risks and catalysts']
    for s in risks:
        for item in s['statements']:statement(item)
        body('Investor use: '+s['investor_use'])
        if s.get('counterevidence'):
            sub('Counterevidence / alternative');statement(s['counterevidence'])
        if s.get('gaps'):note('Remaining evidence: '+'; '.join(s['gaps']))
    story.append(table([['Monitoring item','Investor use / evidence needed'],
        ['Volume and pricing','Test whether reported sales growth is supported by volumes, price/mix and distribution. Watch management guidance against subsequent delivery.'],
        ['Margins and reinvestment','Assess whether cost relief or product mix persists after advertising, capex and maintenance requirements. Do not extrapolate a temporary input-cost benefit.'],
        ['Cash generation','Reconcile earnings with operating cash, inventory, receivables and payables. Distinguish structural cash improvement from a temporary release.'],
        ['Capital allocation and claims','Review acquisition economics, dividends, leases, minority claims and changes in the balance sheet. A valuation bridge can be wrong even when operating forecasts are reasonable.'],
        ['Valuation expectations','Stress capital cost, terminal returns, growth and selected multiples. A gap to a dated market price is an investigation prompt, not proof of mispricing.']],[130,CONTENT-130]))
    note('These monitoring conditions are an analyst framework. They are not predictions that a particular risk or catalyst will occur. No unverified catalyst date is invented.')

    section('10  Research conclusion')
    body(val.get('summary','A justified valuation conclusion is not available.'))
    body('Research stance: no unqualified buy/sell rating is assigned. Use the valuation range to identify the assumptions that would make an investment attractive, then test those assumptions against the operating and cash-flow evidence.')
    if raw.get('discovery'):body('The principal finding should be weighed against the counterargument and falsification condition, not treated as a standalone investment signal.')
    else:body('The evidence does not yet support a confirmed non-obvious thesis. Financial estimates remain conditional, and a wide range or incomplete corroboration should lead to further investigation rather than forced precision.')
    if incomplete:body('The latest research or online coverage is incomplete. This prevents a final, fully corroborated investment conclusion even though newly calculated financial scenarios are available.')
    if data.get('coverage'):
        sub('Analysis coverage - completed work and remaining evidence')
        story.append(table([['Area','Evidence / model coverage']]+[[a['area'],{'complete':'Completed within stated scope','partial':'Partial - see remaining work below','missing':'Missing - no validated assessment'}.get(a.get('status'), 'Completed within stated scope' if a['covered'] else 'Missing - no validated assessment')] for a in data['coverage']['areas']],[160,CONTENT-160]))
        for a in data['coverage']['areas']:
            if not a['covered']:note(a['area']+': '+a['next_action'])
        note('Open sections require company-specific cited interpretation and contrary evidence; news assessment must establish dates and exposure. Targeted questions appear in Appendix D. '+data['coverage']['meaning'])
    note('Company-specific input gaps and balance-sheet/market qualifications are retained in Appendix C.')

    section('Appendix A  Sources and evidence trail')
    # Appendix-only retrieval material follows the references first used in the body.
    for item in targeted.get('topics',[]):
        for e in item.get('excerpts',[]):source(str(e['document_id']),e['title'],'http://127.0.0.1:8000'+e['url'],e['page'])
    for audit in targeted.get('retrieval_audit',[]):
        for original in audit.get('originals',[]):
            for e in original.get('excerpts',[]):source(str(e['document_id']),e['title'],'http://127.0.0.1:8000'+e['url'],e['page'])
    note('Superscript numbers link to this source list. Open a source to inspect the original page. Local links require the Finova server.')
    for item in sources.values():
        title=escape(str(item['code'])+'. '+clean(item['title']))
        if safe_url(item['url']):title=f'<link href={quoteattr(item["url"])} color="#147D73">{title}</link>'
        pages=' | PDF page(s): '+', '.join(sorted(item['pages'])) if item['pages'] else ''
        story.append(Paragraph(f'<a name="reference-{item["code"]}"/>'+title+escape(pages),STYLES['small']))
    if not sources:body('No cited original sources were available in this snapshot.')
    provenance_start=len(story)
    sub('Model provenance')
    body('Research started '+ist(data['started_at'])+'. Financial inputs packaged '+ist(data.get('inputs_created_at'))+'.')
    story.append(link('Editable Excel model used for all valuation and forecast tables',data['workbook_url'],'small'))
    note('The report is a fixed snapshot. Edit assumptions in Excel for live recalculation; run the website report again to create a new PDF and new workbook. Previously generated PDFs are not relabelled as current.')
    story[provenance_start:]=[KeepTogether(story[provenance_start:])]

    section('Appendix B  Assumption audit')
    body('Historical reported figures, external observations, management guidance and analyst estimates are different evidence categories. The assumptions below retain the source type and dates used in the workbook. A new calculation does not turn an older assumption into a newly researched fact.')
    drivers={'volume_growth','price_mix_growth','direct_revenue_growth','ebitda_margin','tax_rate','capex_ratio','nwc_ratio','risk_free_rate','beta','equity_risk_premium','debt_weight','terminal_growth','terminal_roic','terminal_roe','dividend_payout','selected_pe','selected_ev_ebitda'}
    by_driver=OrderedDict()
    driver_labels={'beta':'Levered beta','capex_ratio':'Capex / revenue','nwc_ratio':'Core trade working capital / revenue',
        'terminal_roic':'Terminal ROIC','terminal_roe':'Terminal ROE','selected_pe':'Selected forward P/E',
        'selected_ev_ebitda':'Selected forward EV/EBITDA','direct_revenue_growth':'Revenue growth',
        'debt_weight':'Debt / market capital','ebitda_margin':'Operating EBITDA margin'}
    for a in data.get('assumptions',[]):
        if a['driver'] in drivers:by_driver.setdefault(a['driver'],[]).append(a)
    note('Values run from forecast year 1 to year 5. Full sources, derivations and rationales remain in the editable Excel model.')
    rows=[['Assumption','Bear','Base','Bull','Type / confidence / date']]
    for driver,records in by_driver.items():
        cases={a['scenario']:a for a in records}
        kind='multiple' if driver.startswith('selected_') else 'number' if driver=='beta' else 'pct'
        values=[]
        for case in ('bear','base','bull'):
            record=cases.get(case)
            if not record:values.append('Not available');continue
            series=[fmt(float(v) if v is not None else None,kind) for v in record['values']]
            values.append(series[0]+' (all years)' if len(set(series))==1 else ', '.join(series))
        metadata=list(dict.fromkeys(readable(a['source_type'])+' / '+readable(a['confidence'])+' / '+str(a['source_date']) for a in records))
        rows.append([driver_labels.get(driver,driver.replace('_',' ').capitalize()),*values,'\n'.join(metadata)])
    if len(rows)>1:story.append(table(rows,[115,80,80,80,CONTENT-355],padding=6))

    section('Appendix C  Method selection and coverage gaps')
    rows=[['Method','Selected?','Reason / role']]
    for m in data['methods']:rows.append([m['method'],m['applicable'],m.get('reason','')])
    story.append(table(rows,[105,60,CONTENT-165]))
    sub('Sections not treated as established analysis')
    body('Banking ratio analysis, bank funding/ALM, regulatory bank capital and digital-banking strategy are not applicable to this FMCG framework. Shareholding-pattern analysis, technical analysis, market sentiment, transaction analysis, NAV or residual income require their own suitable evidence; they are not added merely to create a longer report.')
    body('Peer and transaction work requires matching periods, category economics and independently sourced observations. A selected multiple range without those inputs remains an analyst stress case. Governance, moat and management assessments require cited company-specific evidence; missing evidence is not a favourable assessment.')
    qualifications=[*raw.get('financial_data_gaps',[])[:8],*data.get('market_notes',[])[:5]]
    if qualifications:
        qualification_start=len(story)
        sub('Company-specific model qualifications')
        for text in qualifications:note(text)
        story[qualification_start:]=[KeepTogether(story[qualification_start:])]

    if targeted:
        section('Appendix D  Targeted evidence and unresolved questions')
        note('Open research questions and remaining evidence gaps. Original documents are linked in Appendix A; full retrieval records remain available in the saved investigation.')
        rows=[['Research area','Question / coverage']]
        for t in targeted.get('topics',[]):rows.append([t['topic'],t['question']+'\n'+t['status']])
        if len(rows)>1:story.append(table(rows,[135,CONTENT-135]))
        for gap in targeted.get('unresolved',[]):note('Unresolved: '+gap)

    def page(canvas,doc):
        canvas.saveState()
        if doc.page==1:
            canvas.setFillColor(TEAL);canvas.rect(0,HEIGHT-14,WIDTH,14,fill=1,stroke=0)
        else:
            canvas.setFont('Research-Bold',8);canvas.setFillColor(TEAL);canvas.drawString(MARGIN,HEIGHT-29,'FINOVA')
            canvas.setFont('Research',8);canvas.setFillColor(GREY);canvas.drawRightString(WIDTH-MARGIN,HEIGHT-29,company[:65])
            canvas.setStrokeColor(LINE);canvas.line(MARGIN,HEIGHT-38,WIDTH-MARGIN,HEIGHT-38)
        canvas.setFont('Research',8);canvas.setFillColor(GREY)
        canvas.drawString(MARGIN,24,'Team 123  |  '+('Validation report' if validation else 'Layout preview' if preview else 'Company research'))
        canvas.drawRightString(WIDTH-MARGIN,24,str(doc.page));canvas.restoreState()
    doc=Document(str(target),pagesize=A4,leftMargin=MARGIN,rightMargin=MARGIN,topMargin=55,bottomMargin=45,title=company+' - Financial analysis and valuation',author='Finova - Team 123')
    frame=lambda:Frame(MARGIN,45,CONTENT,HEIGHT-100,id='content',leftPadding=0,rightPadding=0,topPadding=0,bottomPadding=0)
    doc.addPageTemplates([PageTemplate(id='Cover',frames=[frame()],onPage=page),PageTemplate(id='Body',frames=[frame()],onPage=page)])
    doc.multiBuild(story)
    reader=PdfReader(target)
    texts=[p.extract_text() or '' for p in reader.pages]
    assert cover_matches(company,texts)
    assert 'Appendix C' in '\n'.join(texts)
    assert len(reader.pages)>=12
    report={'pages':len(reader.pages),'sections':sections,'cover_and_contents_verified':True,
            'source_links':sum(len(p.get('/Annots',[])) for p in reader.pages),'valuation_source':'Excel saved formula values; no PDF valuation formulas',
            'visuals':'Historical sales, earnings, margins, CFO/profit, capex/cash, valuation scenarios and forecast scenarios',
            'targeted_topics':len(targeted.get('topics',[]))}
    target.with_suffix('.verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--input',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    build(json.loads(Path(args.input).read_text(encoding='utf-8')),Path(args.out))
