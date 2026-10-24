import copy
import unittest
from unittest.mock import patch
from backend import sector_comparison as s


def package(company):
    ref={'file':'report.pdf','pages':'3','url':'/documents/1/original#page=3','sha256':'a'*64}
    def period(year,scope='consolidated · total operations',days=365):
        return {'start':f'{year-1}-04-01','end':f'{year}-03-31','duration_days':days,
                'scope':scope,'accounting_scope':'consolidated',
                'values':{'revenue':100*year,'ebitda':20*year,'net_income':10*year,'cfo':12*year,'debt':0,'cash':5*year},
                'sources':{k:[copy.deepcopy(ref)] for k in ('revenue','ebitda','net_income','cfo','debt','cash')}}
    return {'company_id':company,'company':company,'periods':['2026-03-31'],
            'market':{'accounting_scope':'consolidated'},'historical_statements':{'periods':[period(2025),period(2026)]}}


class ComparisonTests(unittest.TestCase):
    def build(self,p):
        with patch.object(s.json,'loads',return_value={'hul':'HUL','itc':'ITC'}):
            return s.build(p,lambda c:package(c))

    def test_source_inputs_are_not_approved_valuation_peers(self):
        out=self.build(package('hul'))
        self.assertEqual(len(out['rows']),2)
        for r in out['rows']:
            self.assertFalse(r['valuation_peer_approved'])
            self.assertNotIn('capex',r['values'])
            self.assertEqual(r['values']['debt'],0)
            self.assertIn('prior_revenue',r['values'])
            self.assertNotIn('metrics',r) # ratios must be Excel results
        self.assertIn('segment',out['rows'][1]['reason'])

    def test_changed_scope_does_not_establish_growth(self):
        p=package('hul');p['historical_statements']['periods'][0]['scope']='consolidated · continuing operations'
        r=self.build(p)['rows'][0]
        self.assertNotIn('prior_revenue',r['values']);self.assertIsNone(r['prior_end'])

    def test_15_month_period_does_not_become_an_annual_peer(self):
        p=package('hul');p['historical_statements']['periods'][-1]['duration_days']=456
        self.assertEqual([r['company_id'] for r in self.build(p)['rows']],['itc'])

    def test_unlinked_fact_is_excluded_instead_of_zero(self):
        p=package('hul');p['historical_statements']['periods'][-1]['sources']['cfo'][0]['url']='javascript:bad'
        r=self.build(p)['rows'][0]
        self.assertNotIn('cfo',r['values']);self.assertNotIn('cfo',r['sources'])

    def test_ambiguous_latest_basis_excluded(self):
        p=package('hul');p['historical_statements']['periods'].append(copy.deepcopy(p['historical_statements']['periods'][-1]))
        self.assertEqual([r['company_id'] for r in self.build(p)['rows']],['itc'])

    def test_missing_prior_year_is_not_a_growth_rate(self):
        p=package('hul');p['historical_statements']['periods'][0]['end']='2024-03-31'
        self.assertNotIn('prior_revenue',self.build(p)['rows'][0]['values'])
