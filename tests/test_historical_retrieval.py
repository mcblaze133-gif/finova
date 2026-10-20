"""History must survive relevance ranking and model context limits."""
import unittest
from backend import investigation,research,company_updates
from backend import storage
from test_backend_audit import AuditFixture


class HistoricalRetrievalTests(unittest.TestCase):
    def rows(self):
        return [{'id':year*100+n,'document_id':year*100+n,'period_sort_hint_unverified':[year,0],
                 'text':('revenue margin guidance '*n)* (10 if year==26 else 1),
                 'pdf_page':1,'original_page':1,'publication_date':None,'original_url':'file:///fixture.pdf',
                 'source_file':f'{year}-{n}.pdf'} for year in range(22,27) for n in range(1,4)]

    def test_high_scoring_recent_pages_do_not_exclude_older_years(self):
        rows=investigation.search_prepared(self.rows(),'revenue margin guidance',10)
        self.assertEqual({r['period_sort_hint_unverified'][0] for r in rows},set(range(22,27)))
        self.assertEqual(len(rows),10)

    def test_small_budget_keeps_oldest_and_newest_without_inventing_dates(self):
        rows=investigation.search_prepared(self.rows(),'revenue',2)
        self.assertEqual([r['period_sort_hint_unverified'][0] for r in rows],[22,26])
        passages=research.safe_passages(rows,6000,per_passage_limit=2000)
        self.assertTrue(all(p['publication_date'] is None for p in passages))

    def test_unknown_period_does_not_displace_the_latest_known_group(self):
        rows=self.rows()+[{'id':999,'document_id':999,'text':'revenue '*100,'period_sort_hint_unverified':None}]
        selected=investigation.search_prepared(rows,'revenue',2)
        self.assertEqual([r['period_sort_hint_unverified'][0] for r in selected],[22,26])

    def test_seed_excerpts_fit_all_five_years(self):
        rows=self.rows()
        for r in rows:r['text']='revenue '*2000
        rows=investigation.search_prepared(rows,'revenue',12)
        result=research.safe_passages(rows,per_passage_limit=2200)
        self.assertEqual(len(result),12)
        self.assertEqual({r['period_sort_hint_unverified'][0] for r in result},set(range(22,27)))

    def test_online_baseline_excerpts_include_old_and_new_periods(self):
        snippets=company_updates.local_excerpts(self.rows())
        self.assertEqual({r['period_sort_hint_unverified'][0] for r in snippets},set(range(22,27)))


class HistoricalCalculationTests(AuditFixture,unittest.TestCase):
    def seed(self):
        self.run_row('history','2026-10-19T12:00:00+00:00')
        with storage.database() as db:
            doc=db.execute("INSERT INTO documents(company,title,original_url,retrieved_at,sha256,local_path) VALUES('hul','Synthetic annual history','https://example.test/history',?,'fixture','fixture.pdf')",(storage.now(),)).lastrowid
            ids=[]
            for year in range(2022,2027):
                passage=db.execute('INSERT INTO passages(document_id,pdf_page,text) VALUES(?,?,?)',(doc,year-2021,f'Synthetic revenue {year}')).lastrowid
                ids.append(passage)
                db.execute("INSERT INTO facts(passage_id,metric,value_decimal,unit,currency,period_start,period_end,accounting_scope,operations_scope,definition,source_quote,validation_status) VALUES(?,'revenue',?,'INR_crore','INR',?,?,'consolidated','total','revenue from operations','Synthetic fixture only','validated')",(passage,str(100+(year-2022)*10),f'{year}-01-01',f'{year}-12-31'))
        return ids

    def test_current_and_older_comparable_growth_are_both_calculated(self):
        ids=self.seed()
        _,calculations=research.available_calculations('hul',set(ids),'history')
        self.assertEqual(len(calculations),2)
        self.assertEqual([c['periods'][0]['end'] for c in calculations],['2026-12-31','2023-12-31'])
        self.assertEqual(calculations[1]['value'],'10.0')
        valid,calculations=research.available_calculations('hul',set(ids),'history')
        context=research.fact_context(valid,calculations)
        self.assertTrue(all('source_quote' not in f for f in context))
        required={i for c in calculations for i in c['input_fact_ids']}
        self.assertTrue(required.issubset({f['id'] for f in context}))
        self.assertEqual(len(research.calculation_context(calculations)),2)

    def test_conflicting_same_period_values_require_reconciliation(self):
        ids=self.seed()
        with storage.database() as db:
            db.execute("INSERT INTO facts(passage_id,metric,value_decimal,unit,currency,period_start,period_end,accounting_scope,operations_scope,definition,source_quote,validation_status) SELECT passage_id,metric,'999',unit,currency,period_start,period_end,accounting_scope,operations_scope,definition,source_quote,validation_status FROM facts WHERE period_end='2026-12-31'")
        valid,calculations=research.available_calculations('hul',set(ids),'history')
        self.assertEqual(sum(f.get('calculation_input_eligible') is False for f in valid),2)
        self.assertTrue(all(i['period_end']!='2026-12-31' for c in calculations for i in c['inputs']))
