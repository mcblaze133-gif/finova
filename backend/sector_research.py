"""Independent, source-checked sector assessments; discovery failure cannot erase them."""
import asyncio,json,re
from typing import Literal
from pydantic import Field
from backend import research as r, investigation as inv, storage, model

QUERIES={
 'Business and products':'brands products portfolio categories distribution business',
 'Demand, volume and pricing':'volume price mix demand rural urban growth',
 'Costs and profitability':'EBITDA margin raw material advertising costs profitability',
 'Segments and geography':'segment revenue results geographic domestic international',
 'Competition and economic moat':'market share competitors brands competitive distribution',
 'Management and governance':'governance related party auditor remuneration contingent litigation',
 'Capital allocation':'capital expenditure acquisition dividend cash reinvestment',
 'Risks and catalysts':'risk outlook capacity expansion regulatory competition',
 'Macro and commodity exposure':'commodity inflation palm wheat milk sugar currency freight',
}
class Assessment(r.Strict):
 topic:Literal[tuple(QUERIES)]
 statements:list[r.Statement]=Field(max_length=2)
 counterevidence:r.Statement|None=None
 investor_use:str=Field(min_length=15,max_length=600)
 gaps:list[str]=Field(max_length=4)
class Assessments(r.Strict):
 assessments:list[Assessment]=Field(min_length=9,max_length=9)
class Repairs(r.Strict):
 assessments:list[Assessment]=Field(min_length=1,max_length=3)
class Decision(r.Strict):
 topic:Literal[tuple(QUERIES)]
 verdict:Literal['supported','partial','rejected']
 reason:str=Field(min_length=10,max_length=600)
class Decisions(r.Strict):
 decisions:list[Decision]=Field(min_length=9,max_length=9)

def unique(items):
 if len({x.topic for x in items})!=len(QUERIES):raise ValueError('Each research area must be assessed exactly once.')

async def repair_missing(checked,selected,temporal,company,run_id,audit,events=()):
 """One bounded retry for empty/invalid sections; never regenerate valid siblings."""
 targets=[s.topic for s in checked if not s.statements][:3]
 if not targets:return checked
 audit['repair']={'targets':targets,'status':'not_completed'}
 try:
  model.require_capacity(2) # retain room for the ordinary critic, daily cap unchanged
  repair=await asyncio.wait_for(model.generate(run_id,'sector-repair',
      {'company':company,'topics':targets,'temporal_scope':temporal,
       'passages':r.excerpt_context(selected)},Repairs),120)
  if len(repair.assessments)!=len(targets) or {s.topic for s in repair.assessments}!=set(targets):
   raise ValueError('Repair topics do not match the requested missing areas.')
  replacements={}
  for section in repair.assessments:
   from backend import scope_events
   for statement in section.statements:
    r.check_statement(statement,selected);scope_events.check(statement.text,events)
   if section.counterevidence:
    r.check_statement(section.counterevidence,selected);scope_events.check(section.counterevidence.text,events)
   replacements[section.topic]=section
  audit['repair']['status']='citation_checked; critic still required'
  return [replacements.get(s.topic,s) for s in checked]
 except (model.ModelUnavailable,ValueError,OSError,TimeoutError) as exc:
  audit['repair']['error']=str(exc) or 'Repair time budget reached; valid sections retained.'
  return checked

def selected_passages(rows):
 selected={};audit=[]
 for topic,q in QUERIES.items():
  ids=[]
  for side,query in [('support',q),('challenge',q+' decline pressure risk uncertainty impairment')]:
   hits=inv.search_prepared(rows,query,3)
   for hit in hits:
    # Centre a bounded excerpt on the topic rather than the opening of a long page.
    from backend.research_gaps import excerpt
    item=excerpt(hit,query)
    text=item['quote']
    correction=re.search(r'if I may correct|let me correct|to clarify|for clarity',hit['text'],re.I)
    if correction and topic=='Costs and profitability':
     # Preserve the response correcting an interviewer's premise rather than
     # presenting the opening question as management guidance.
     start=max(0,correction.start()-180)
     text=hit['text'][start:start+1400]
    if 'Reviewed financial record index' in hit['text']:continue
    if r.normalized(text) not in r.normalized(hit['text']):continue
    if hit['id'] not in selected:selected[hit['id']]=dict(hit,text=text[:1400])
    ids.append(hit['id'])
   audit.append({'topic':topic,'side':side,'passage_ids':[h['id'] for h in hits]})
 return list(selected.values()),audit

async def complete(payload,run_id):
 raw=payload['research'];audit={'version':1,'started_at':storage.now(),'status':'partial','areas':[]}
 from backend import scope_events
 events=[]
 raw['section_analysis']=audit
 try:
  rows,proof=await asyncio.to_thread(inv.prepared_passages,payload['company_id'])
  # Include originals actually retrieved by this report's targeted public search.
  public_ids={e['passage_id'] for a in payload.get('targeted_research',{}).get('retrieval_audit',[]) for o in a.get('originals',[]) if o.get('status')=='original_read' for e in o.get('excerpts',[])}
  for pid in public_ids:
   found=storage.rows('SELECT p.id,p.document_id,p.pdf_page,p.text,d.company,d.title,d.original_url,d.publication_date,d.sha256 FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.id=? AND d.company=?',(pid,payload['company_id']))
   rows.extend(found)
  selected,searches=selected_passages(rows)
  # Reviewed documentary clarifications must reach the analyst as well as the
  # rendered report. Validate the original bytes and quotation before inclusion.
  from backend import source_reviews
  for review in source_reviews.build(payload['company_id']):
   for ref in review.get('evidence',[]):
    found=next((p for p in rows if p['document_id']==ref['document_id'] and p['pdf_page']==ref['page']),None)
    if found and r.normalized(ref['quote']) in r.normalized(found['text']):
     selected=[p for p in selected if p['id']!=found['id']]
     selected.append(dict(found,text=ref['quote'][:1400]))
  from backend import public_sources
  external=public_sources.passages(raw.get('registered_source_refresh',{}),'competition market position margins demand capital risks outlook',6)
  selected.extend(external)
  from backend import scope_events
  events=await asyncio.to_thread(scope_events.load,payload['company_id'])
  selected=list({p['id']:p for p in [*selected,*[e['passage'] for e in events]]}.values())
  raw['passages']=list({p['id']:p for p in [*selected,*raw.get('passages',[])]}.values())
  raw['sources']=storage.rows('SELECT id,title,original_url,publication_date,retrieved_at,sha256 FROM documents WHERE company=?',(payload['company_id'],))
  # Per-topic catalog keeps each call below the model context budget.
  audit.update(pack_signature=proof['signature'],searches=searches,passage_catalog=selected)
  catalog=r.excerpt_context(selected)
  temporal={'as_of':storage.today_ist().isoformat(),
            'reviewed_scope_events':[{k:v for k,v in e.items() if k!='passage'} for e in events],
            'historical_periods':[{k:p.get(k) for k in ('start','end','scope','qualification')} for p in payload.get('history',{}).get('periods',[])],
            'rule':'Attribute every disclosure to its actual period. Older evidence is historical context, not current group strategy. Check demergers/disposals and discontinued operations before describing a segment as owned today. An undated passage cannot establish a current fact. Compare like periods and scopes; do not infer a moat from generic brand language, sales growth or unrelated FX risk.'}
  context={'company':payload['company'],'topics':list(QUERIES),'passages':catalog,'topic_searches':searches,'temporal_scope':temporal,
           'news':r.online_context(raw.get('external_updates',{})),
           'instructions':'Complete all nine areas independently. Write connected company-specific paragraphs, using two or three sentences per statement when the evidence supports that depth. Include the relevant reporting period and distinguish a disclosed fact from its economic interpretation. Explain the operating mechanism and how an investor could test it, without generic filler or repeating document titles in the narrative; citations are rendered in the appendix. Do not generalise a pricing arrangement for specified related-party transactions to all company procurement. A disclosure of controls or no material conflicts is not evidence of actual misconduct. Missing evidence is a gap, not an invitation to invent facts.'}
  draft=await asyncio.wait_for(model.generate(run_id,'sector',context,Assessments),120);unique(draft.assessments)
  checked=[];citation_errors={}
  for section in draft.assessments:
   errors=[];valid=[]
   for statement in section.statements:
    try:r.check_statement(statement,selected);scope_events.check(statement.text,events);valid.append(statement)
    except ValueError as exc:errors.append(str(exc))
   section.statements=valid
   if section.counterevidence:
    try:r.check_statement(section.counterevidence,selected);scope_events.check(section.counterevidence.text,events)
    except ValueError as exc:section.counterevidence=None;errors.append(str(exc))
   section.gaps.extend(errors[:max(0,4-len(section.gaps))])
   citation_errors[section.topic]=errors
   checked.append(section)
  checked=await repair_missing(checked,selected,temporal,payload['company'],run_id,audit,events)
  # A repaired section has passed a new exact citation check. Earlier invalid
  # draft citations stay recorded, but cannot incorrectly reject the replacement.
  if audit.get('repair',{}).get('status','').startswith('citation_checked'):
   for section in checked:
    if section.topic in audit['repair']['targets'] and section.statements:citation_errors[section.topic]=[]
  # Do not lose checked work if the separate model critic fails.
  audit['draft_areas']=[s.model_dump(mode='json') for s in checked]
  def compact(value):
   if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if k!='quote'}
   if isinstance(value,list):return [compact(v) for v in value]
   return value
  cited={c.passage_id for s in checked for statement in [*s.statements,*([s.counterevidence] if s.counterevidence else [])] for c in statement.citations}
  # The critic reviews the actual claims and their cited originals. Unused
  # retrieval candidates remain in the audit, without duplicating a large
  # search catalog alongside the full nine-area assessment.
  critic_catalog=[p for p in catalog if p['id'] in cited]
  critic=await asyncio.wait_for(model.generate(run_id,'sector-review',{'company':payload['company'],'assessments':compact([s.model_dump(mode='json') for s in checked]),'passages':critic_catalog,'temporal_scope':temporal,
      'instructions':'Reject unsupported current-tense conclusions from old or undated evidence. Require the stated reporting period and ownership/scope, a direct economic mechanism, and a relevant counterargument. Multiple issuer documents are not independent corroboration. Mark genuine missing market-share evidence partial rather than accepting confident leadership language.'},Decisions),120)
  unique(critic.decisions);decisions={d.topic:d for d in critic.decisions}
  audit['critic']=critic.model_dump(mode='json')
  published=[]
  for section in checked:
   decision=decisions[section.topic]
   state='missing' if not section.statements or decision.verdict=='rejected' else 'complete' if decision.verdict=='supported' and not citation_errors[section.topic] else 'partial'
   area=section.model_dump(mode='json')|{'status':state,'review_reason':decision.reason,'reviewed':True,'review_verdict':decision.verdict,'citation_errors':citation_errors[section.topic]}
   audit['areas'].append(area)
   if state!='missing':published.append(area)
  raw['sector_sections']=published
  raw['passages']=list({p['id']:p for p in [*selected,*raw.get('passages',[])]}.values())
  audit['status']='complete' if all(a['status']=='complete' for a in audit['areas']) else 'partial'
 except (model.ModelUnavailable,ValueError,OSError,TimeoutError) as exc:
  if isinstance(exc,scope_events.ScopeEvidenceError):raise
  audit['error']=str(exc) or 'Section assessment time budget reached; completed checks retained.'
  # Retain per-topic checked drafts as partial, never silently mark them reviewed.
  if audit.get('draft_areas'):
   audit['areas']=[a|{'status':'partial' if a['statements'] else 'missing','reviewed':False,'review_reason':'Independent section review did not complete.'} for a in audit['draft_areas']]
   raw['sector_sections']=[a for a in audit['areas'] if a['statements']]
 scope_events.filter_research(raw,events)
 audit['finished_at']=storage.now()
 calls=storage.rows('SELECT model_calls FROM research_runs WHERE id=?',(run_id,))[0]['model_calls'];raw['model_calls']=calls
 with storage.database() as db:db.execute("UPDATE research_runs SET report_json=?,updated_at=?,stage='finished' WHERE id=?",(json.dumps(raw),storage.now(),run_id))
 return audit
