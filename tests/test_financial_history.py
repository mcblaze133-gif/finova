import unittest
from unittest.mock import patch
from backend import financial_history
from backend.valuation_spec import FinancialRecord

class FinancialHistoryTests(unittest.TestCase):
    def record(self, **extra):
        return FinancialRecord.model_validate(dict(company='nestle-india',metric='revenue',value='100',unit='INR_crore',
            period_start='2023-01-01',period_end='2024-03-31',accounting_scope='standalone',operations_scope='total',
            definition='Synthetic reported value',source_type='historical',source_file='test.pdf',source_page='2',
            source_url='https://example.org/test.pdf',source_date='2024-04-30',review_status='user_verified',**extra))

    def build(self,records):
        with patch('backend.financial_history.storage.rows',return_value=[]):return financial_history.build('nestle-india',records)

    def test_nonannual_period_preserved_and_stock_scope_matched(self):
        r=self.record()
        stock=r.model_copy(update={'metric':'cash','period_start':None})
        other=stock.model_copy(update={'accounting_scope':'consolidated','value':'999'})
        p=self.build([r,stock,other])['periods'][0]
        self.assertEqual(p['duration_days'],456)
        self.assertEqual(p['values']['revenue'],1000000000)
        self.assertEqual(p['values']['cash'],1000000000)
        self.assertIn('not annualised',p['qualification'])

    def test_conflicting_values_are_excluded_not_selected(self):
        r=self.record();h=self.build([r,r.model_copy(update={'value':'101'})])
        self.assertNotIn('revenue',h['periods'][0]['values'])
        self.assertTrue(h['issues'])

    def test_duplicate_evidence_does_not_double_amount(self):
        r=self.record();h=self.build([r,r])
        self.assertEqual(len(h['periods']),1)
        self.assertEqual(h['periods'][0]['values']['revenue'],1000000000)

    def test_quarter_not_presented_as_annual_history(self):
        from datetime import date
        r=self.record().model_copy(update={'period_start':date(2024,1,1)})
        self.assertEqual(self.build([r])['periods'],[])
