"""Run with the bundled PDF Python: chart integrity, not financial revaluation."""
import unittest
try:
    from tools.build_research_report import trend_chart,scope_breaks,cover_matches,referenced_paragraph
    AVAILABLE=True
except ModuleNotFoundError:
    AVAILABLE=False

@unittest.skipUnless(AVAILABLE,'PDF renderer is in the bundled PDF Python')
class ChartTests(unittest.TestCase):
    def test_long_company_name_may_wrap_on_cover(self):
        self.assertTrue(cover_matches('Tata Consumer Products Limited',['Tata Consumer Products\nLimited','Contents']))
        self.assertFalse(cover_matches('Tata Consumer Products Limited',['Hindustan Unilever Limited','Contents']))
        self.assertFalse(cover_matches('Tata Consumer Products Limited',['Tata Consumer Products Limited']))

    def test_labels_cannot_be_overwritten_by_metric_dictionary(self):
        with self.assertRaisesRegex(ValueError,'align exactly'):
            trend_chart({'revenue':'Revenue'},[('Cash',[1,2])])

    def test_series_requires_one_point_per_period(self):
        with self.assertRaises(ValueError):trend_chart(['2025','2026'],[('Cash',[2])])

    def test_scope_and_transition_periods_break_connected_trends(self):
        periods=[{'scope':'total','duration_days':365},{'scope':'continuing','duration_days':365},
                 {'scope':'continuing','duration_days':456},{'scope':'continuing','duration_days':365}]
        self.assertEqual(scope_breaks(periods),[1,2,3])

    def test_missing_observations_are_not_plotted_as_zero(self):
        chart=trend_chart(['2025','2026'],[('Cash',[None,None])])
        self.assertIn('No numeric observations',chart.contents[0].text)

    def test_superscript_references_are_safe_numbered_appendix_links(self):
        p=referenced_paragraph('Sales < profit & cash',[1,2,1])
        self.assertIn('&lt;',p.text)
        self.assertIn('<super',p.text)
        self.assertEqual(p.text.count('#reference-1'),1)
        self.assertIn('#reference-2',p.text)
        with self.assertRaises(ValueError):referenced_paragraph('Claim',['1'])
