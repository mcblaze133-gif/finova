import unittest
from unittest.mock import patch
from backend import sector_research


class TranscriptCorrectionTests(unittest.TestCase):
    def test_cost_excerpt_preserves_management_correction(self):
        text=('Analyst: Is the margin 13.7%? '+('Context. '*180)+
              'CFO: EBITDA margin, sorry, if I may correct. Our EBITDA margin is 23.3%, '
              'with 24% discussed alongside the Labour Code impact.')
        hit={'id':1,'text':text}
        with patch.object(sector_research,'QUERIES',{'Costs and profitability':'EBITDA margin'}), \
             patch.object(sector_research.inv,'search_prepared',return_value=[hit]), \
             patch('backend.research_gaps.excerpt',return_value={'quote':text[:1400]}):
            selected,_=sector_research.selected_passages([hit])
        self.assertIn('Our EBITDA margin is 23.3%',selected[0]['text'])
        self.assertIn(selected[0]['text'],text)
        self.assertLessEqual(len(selected[0]['text']),1400)

    def test_unrelated_topic_keeps_its_relevant_excerpt(self):
        text='Governance: auditor appointment reviewed. '+('Context. '*180)+'CFO: for clarity, EBITDA is 23.3%.'
        hit={'id':1,'text':text}
        original=text[:100]
        with patch.object(sector_research,'QUERIES',{'Management and governance':'auditor governance'}), \
             patch.object(sector_research.inv,'search_prepared',return_value=[hit]), \
             patch('backend.research_gaps.excerpt',return_value={'quote':original}):
            selected,_=sector_research.selected_passages([hit])
        self.assertEqual(selected[0]['text'],original)
