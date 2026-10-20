"""Independent, source-checked sector assessments; discovery failure cannot erase them."""
import asyncio,json
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
class Decision(r.Strict):
 topic:Literal[tuple(QUERIES)]
 verdict:Literal['supported','partial','rejected']
 reason:str=Field(min_length=10,max_length=600)
class Decisions(r.Strict):
 decisions:list[Decision]=Field(min_length=9,max_length=9)

def unique(items):
 if len({x.topic for x in items})!=len(QUERIES):raise ValueError('Each research area must be assessed exactly once.')

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
    if 'Reviewed financial record index' in hit['text']:continue
    if r.normalized(text) not in r.normalized(hit['text']):continue
    if hit['id'] not in selected:selected[hit['id']]=dict(hit,text=text[:1400])
    ids.append(hit['id'])
   audit.append({'topic':topic,'side':side,'passage_ids':[h['id'] for h in hits]})
 return list(selected.values()),audit

async def complete(payload,run_id):
 raw=payload['research'];audit={'version':1,'started_at':storage.now(),'status':'partial','areas':[]}
 raw['section_analysis']=audit
 try:
  rows,proof=await asyncio.to_thread(inv.prepared_passages,payload['company_id'])
  # Include originals actually retrieved by this report's targeted public search.
  public_ids={e['passage_id'] for a in payload.get('targeted_research',{}).get('retrieval_audit',[]) for o in a.get('originals',[]) if o.get('status')=='original_read' for e in o.get('excerpts',[])}
  for pid in public_ids:
   found=storage.rows('SELECT p.id,p.document_id,p.pdf_page,p.text,d.company,d.title,d.original_url,d.publication_date,d.sha256 FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.id=? AND d.company=?',(pid,payload['company_id']))
   rows.extend(found)
  selected,searches=selected_passages(rows)
  raw['passages']=list({p['id']:p for p in [*selected,*raw.get('passages',[])]}.values())
  raw['sources']=storage.rows('SELECT id,title,original_url,publication_date,retrieved_at,sha256 FROM documents WHERE company=?',(payload['company_id'],))
  # Per-topic catalog keeps each call below the model context budget.
  audit.update(pack_signature=proof['signature'],searches=searches,passage_catalog=selected)
  catalog=r.excerpt_context(selected)
  context={'company':payload['company'],'topics':list(QUERIES),'passages':catalog,'topic_searches':searches,
           'news':r.online_context(raw.get('external_updates',{})),
           'instructions':'Complete all nine areas independently. Write connected company-specific paragraphs, using two or three sentences per statement when the evidence supports that depth. Include the relevant reporting period and distinguish a disclosed fact from its economic interpretation. Explain the operating mechanism and how an investor could test it, without generic filler or repeating document titles in the narrative; citations are rendered in the appendix. Do not generalise a pricing arrangement for specified related-party transactions to all company procurement. A disclosure of controls or no material conflicts is not evidence of actual misconduct. Missing evidence is a gap, not an invitation to invent facts.'}
  draft=await asyncio.wait_for(model.generate(run_id,'sector',context,Assessments),120);unique(draft.assessments)
  checked=[];citation_errors={}
  for section in draft.assessments:
   errors=[];valid=[]
   for statement in section.statements:
    try:r.check_statement(statement,selected);valid.append(statement)
    except ValueError as exc:errors.append(str(exc))
   section.statements=valid
   if section.counterevidence:
    try:r.check_statement(section.counterevidence,selected)
    except ValueError as exc:section.counterevidence=None;errors.append(str(exc))
   section.gaps.extend(errors[:max(0,4-len(section.gaps))])
   citation_errors[section.topic]=errors
   checked.append(section)
  # Do not lose checked work if the independent critic fails.
  audit['draft_areas']=[s.model_dump(mode='json') for s in checked]
  def compact(value):
   if isinstance(value,dict):return {k:compact(v) for k,v in value.items() if k!='quote'}
   if isinstance(value,list):return [compact(v) for v in value]
   return value
  critic=await asyncio.wait_for(model.generate(run_id,'sector-review',{'company':payload['company'],'assessments':compact([s.model_dump(mode='json') for s in checked]),'passages':catalog},Decisions),120)
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
  audit['error']=str(exc) or 'Section assessment time budget reached; completed checks retained.'
  # Retain per-topic checked drafts as partial, never silently mark them reviewed.
  if audit.get('draft_areas'):
   audit['areas']=[a|{'status':'partial' if a['statements'] else 'missing','reviewed':False,'review_reason':'Independent section review did not complete.'} for a in audit['draft_areas']]
   raw['sector_sections']=[a for a in audit['areas'] if a['statements']]
 audit['finished_at']=storage.now()
 calls=storage.rows('SELECT model_calls FROM research_runs WHERE id=?',(run_id,))[0]['model_calls'];raw['model_calls']=calls
 with storage.database() as db:db.execute("UPDATE research_runs SET report_json=?,updated_at=?,stage='finished' WHERE id=?",(json.dumps(raw),storage.now(),run_id))
 return audit
