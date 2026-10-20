"""Bind a report's validated findings to its editable valuation workbook."""
import json,re,hashlib
from backend import storage,research_gaps

def attach(package, report_id):
 if not re.fullmatch('[a-f0-9]{32}',report_id):raise ValueError('Invalid research report identity.')
 jobs=storage.rows('SELECT company,research_run_id FROM analysis_reports WHERE id=?',(report_id,))
 if not jobs or jobs[0]['company']!=package['company_id']:raise ValueError('Research report belongs to a different company.')
 job=jobs[0];runs=storage.rows('SELECT report_json FROM research_runs WHERE id=? AND company=?',(job['research_run_id'],job['company']))
 if not runs or not runs[0]['report_json']:raise ValueError('Matching research is unavailable.')
 raw=json.loads(runs[0]['report_json']);base='http://127.0.0.1:8000'
 update_id=raw.get('update_run_id')
 from backend import company_updates
 news=company_updates.get(job['company'],update_id) if update_id else None
 if (package.get('external_updates') or {}).get('id')!=update_id and update_id:
  raise ValueError('Workbook and report must use the same online update check.')
 coverage=research_gaps.report_coverage({'research':raw,'history':package.get('historical_statements',{}),'news':news,'valuation':{'conditional':True}})
 meta={'report_id':report_id,'research_run_id':job['research_run_id'],'research_updated_at':raw.get('section_analysis',{}).get('finished_at',raw.get('completed_at')),
       'research_sha256':hashlib.sha256(json.dumps(raw,sort_keys=True).encode()).hexdigest(),
       'pdf_url':base+'/analysis-reports/'+report_id+'/pdf?view=true','coverage':coverage}
 package['research_report']=meta
 notes=[{'topic':'Matching research PDF','finding':'This workbook and the linked report belong to the same investigation. Valuation inputs remain editable; the PDF records the results when generated. Excel edits do not automatically rewrite the PDF.',
         'source':'Open matching research PDF','source_url':meta['pdf_url']},
        {'topic':'Research dates','finding':'Operating research updated '+str(meta['research_updated_at'])+'. Financial assumptions retain their separately dated sources. News check: '+str((news or {}).get('checked_at'))+'.','source':'Same-investigation evidence and news review.'}]
 for area in coverage['areas']:
  notes.append({'topic':'Coverage: '+area['area'],'finding':area['status'].capitalize()+'. '+area['next_action'],'source':'Report analysis coverage.'})
 for section in raw.get('sector_sections',[]):
  topic=section['topic']
  for i,statement in enumerate(section.get('statements',[]),1):
   notes.append({'topic':topic+f' - finding {i}','finding':statement['text'],'source':'Source excerpts listed directly below.'})
   for cite in statement['citations']:
    catalog=[*raw.get('passages',[]),*raw.get('section_analysis',{}).get('passage_catalog',[])]
    row=next((p for p in catalog if p['id']==cite['passage_id']),None)
    if not row:raise ValueError('A research finding has no traceable source.')
    url=base+f'/documents/{row["document_id"]}/original#page={row["pdf_page"]}'
    notes.append({'topic':topic+' - source','finding':cite['quote'],'source':row.get('title','Original disclosure')+f', page {row["pdf_page"]}','source_url':url})
  if section.get('counterevidence'):
   statement=section['counterevidence'];notes.append({'topic':topic+' - counterargument','finding':statement['text'],'source':'Cited in the matching PDF; not a separate confirmed discovery.'})
   for cite in statement['citations']:
    row=next((p for p in [*raw.get('passages',[]),*raw.get('section_analysis',{}).get('passage_catalog',[])] if p['id']==cite['passage_id']),None)
    if not row:raise ValueError('Counterevidence has no traceable source.')
    notes.append({'topic':topic+' - counterevidence source','finding':cite['quote'],'source':row.get('title','Original disclosure')+f', page {row["pdf_page"]}',
                  'source_url':base+f'/documents/{row["document_id"]}/original#page={row["pdf_page"]}'})
  notes.append({'topic':topic+' - investor use','finding':section['investor_use'],'source':'Analyst interpretation subject to stated evidence.'})
  if section.get('gaps'):notes.append({'topic':topic+' - remaining evidence','finding':'; '.join(section['gaps']),'source':'Unresolved; not replaced with an assumed fact.'})
 package['research_notes']=[*notes,*package.get('research_notes',[])]
 return package
