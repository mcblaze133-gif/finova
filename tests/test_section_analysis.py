import unittest
import json
from unittest.mock import patch,AsyncMock
from backend import research as r,sector_research as s,research_gaps as g,model
from test_backend_audit import AuditFixture

class Sections(AuditFixture,unittest.IsolatedAsyncioTestCase):
 def setUp(self):
  super().setUp();self.run_row('section-test','2026-10-20T00:00:00+00:00')
  self.text='Company brands products portfolio volume price margin raw material segment geographic market share governance auditor capital expenditure acquisition cash risk commodity inflation. Reported facts require interpretation.'
  self.rows=[dict(id=1,document_id=1,pdf_page=2,text=self.text,company='hul',title='Fixture',original_url='https://example.test/fixture',publication_date=None,sha256='fixture')]
  self.statement={'text':'The company describes its business and operating risks.','citations':[{'passage_id':1,'excerpt_id':0}]}
 def drafts(self,bad=False):
  return s.Assessments(assessments=[dict(topic=t,statements=[self.statement if not bad or i else {'text':'Invalid unsupported statement.','citations':[{'passage_id':999,'excerpt_id':0}]}],counterevidence=None,investor_use='Use this attributed evidence to frame further company research.',gaps=[]) for i,t in enumerate(s.QUERIES)])
 def reviews(self):return s.Decisions(decisions=[dict(topic=t,verdict='supported',reason='The bounded description is supported by the supplied excerpt.') for t in s.QUERIES])
 async def test_critic_receives_all_cited_sources_without_unused_search_candidates(self):
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{}}
  extra=dict(self.rows[0],id=2,text='Uncited retrieval candidate. '*50)
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s,'selected_passages',return_value=([*self.rows,extra],[])),patch.object(s.model,'generate',new=AsyncMock(side_effect=[self.drafts(),self.reviews()])) as generate:
   audit=await s.complete(payload,'section-test')
  self.assertEqual(audit['status'],'complete')
  self.assertEqual({p['id'] for p in generate.await_args_list[0].args[2]['passages']},{1,2})
  self.assertEqual({p['id'] for p in generate.await_args_list[1].args[2]['passages']},{1})
  self.assertEqual({p['id'] for p in audit['passage_catalog']},{1,2})
 async def test_one_bad_section_does_not_erase_other_eight(self):
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{}}
  bad=self.drafts(True)
  repair=s.Repairs(assessments=[bad.assessments[0]])
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s.model,'generate',new=AsyncMock(side_effect=[bad,repair,self.reviews()])):
   audit=await s.complete(payload,'section-test')
  self.assertEqual(len(audit['areas']),9)
  self.assertEqual(audit['areas'][0]['status'],'missing')
  self.assertEqual(sum(a['status']=='complete' for a in audit['areas']),8)
  self.assertEqual(len(payload['research']['sector_sections']),8)
 async def test_critic_failure_retains_checked_drafts_as_partial(self):
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{}}
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s.model,'generate',new=AsyncMock(side_effect=[self.drafts(),model.ModelUnavailable('Fixture unavailable')])):
   audit=await s.complete(payload,'section-test')
  self.assertEqual(len(audit['areas']),9)
  self.assertTrue(all(a['status']=='partial' and not a['reviewed'] for a in audit['areas']))
  self.assertTrue(payload['research']['passages'])
 def test_invalid_timeline_keeps_supported_operating_section(self):
  a=r.Analysis(sufficient=True,discovery=self.statement,significance=[self.statement]*3,timeline=[dict(date='2026-10-20',**self.statement)],counterargument=self.statement,falsification_condition='A later disclosure may contradict the proposed interpretation.',limitations=[],sector_sections=[dict(topic='Business and products',statements=[self.statement],investor_use='Use the described operating scope to choose relevant comparisons.')])
  errors=r.isolate_analysis(a,self.rows)
  self.assertTrue(errors);self.assertFalse(a.timeline);self.assertEqual(len(a.sector_sections),1)
  r.check_statements(a,self.rows)
 def test_coverage_distinguishes_partial_statements_and_assessed_news(self):
  p={'history':{'periods':[{'values':{'revenue':100}}]},'news':{'status':'assessed_with_unverified_sources','result':{'events':[{}]}},'research':{},'valuation':{'weighted':{}}}
  areas={a['area']:a for a in g.report_coverage(p)['areas']}
  self.assertEqual(areas['Financial statements']['status'],'partial')
  self.assertEqual(areas['Current developments']['status'],'partial')
  self.assertEqual(areas['Management and governance']['status'],'missing')
 async def test_scoped_supported_assessment_can_disclose_nonessential_limits(self):
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{}}
  drafts=self.drafts()
  for area in drafts.assessments:area.gaps=['No independent causal conclusion is established.']
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s.model,'generate',new=AsyncMock(side_effect=[drafts,self.reviews()])):
   audit=await s.complete(payload,'section-test')
  self.assertTrue(all(a['status']=='complete' for a in audit['areas']))
  self.assertTrue(all(a['gaps'] for a in audit['areas']))
  self.assertTrue(audit['critic'])
 def test_malformed_section_does_not_discard_valid_siblings(self):
  data=self.drafts().model_dump(mode='json');data['assessments'][0]['investor_use']='x'
  parsed=model.validated_response('sector',s.Assessments,json.dumps(data))
  self.assertEqual(len(parsed.assessments),9)
  self.assertFalse(parsed.assessments[0].statements)
  self.assertTrue(all(x.statements for x in parsed.assessments[1:]))
 def test_topic_duplicates_rejected(self):
  draft=self.drafts();draft.assessments[1].topic=draft.assessments[0].topic
  with self.assertRaises(ValueError):s.unique(draft.assessments)
 async def test_reviewer_receives_dates_and_reporting_scope(self):
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{},
           'history':{'periods':[{'start':'2025-04-01','end':'2026-03-31','scope':'consolidated continuing operations','qualification':'Prior disposals affect comparability.'}]}}
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s.model,'generate',new=AsyncMock(side_effect=[self.drafts(),self.reviews()])) as generate:
   await s.complete(payload,'section-test')
  for call in generate.await_args_list:
   temporal=call.args[2]['temporal_scope']
   self.assertEqual(temporal['historical_periods'][0]['end'],'2026-03-31')
   self.assertIn('disposals',temporal['rule'])
   self.assertIn('undated',temporal['rule'])
 async def test_missing_section_gets_one_source_checked_repair_before_review(self):
  draft=self.drafts();draft.assessments[2].statements=[]
  replacement=self.drafts().assessments[2]
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{}}
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s.model,'generate',new=AsyncMock(side_effect=[draft,s.Repairs(assessments=[replacement]),self.reviews()])) as generate:
   audit=await s.complete(payload,'section-test')
  self.assertEqual([call.args[1] for call in generate.await_args_list],['sector','sector-repair','sector-review'])
  self.assertEqual(sum(a['status']=='complete' for a in audit['areas']),9)
  self.assertEqual(audit['repair']['targets'],['Costs and profitability'])
  self.assertTrue(audit['critic'])
 async def test_failed_repair_keeps_valid_siblings_and_runs_critic(self):
  draft=self.drafts();draft.assessments[2].statements=[]
  payload={'company_id':'hul','company':'Hindustan Unilever Limited','research':{}}
  with patch.object(s.inv,'prepared_passages',return_value=(self.rows,{'signature':'fixture'})),patch.object(s.model,'generate',new=AsyncMock(side_effect=[draft,model.ModelUnavailable('Repair unavailable'),self.reviews()])):
   audit=await s.complete(payload,'section-test')
  self.assertEqual(sum(a['status']=='complete' for a in audit['areas']),8)
  self.assertEqual(audit['areas'][2]['status'],'missing')
  self.assertIn('Repair unavailable',audit['repair']['error'])
