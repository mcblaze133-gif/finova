"""The five-company source registry must survive a clean local database."""
import json
import unittest
from unittest.mock import patch
from backend.companies import profiles, resolve


class CompanyProfileTests(unittest.TestCase):
    def test_five_source_profiles_available_without_custom_database_rows(self):
        with patch('backend.storage.rows', return_value=[]):
            for company in ('britannia','hul','itc','nestle-india','tata-consumer'):
                profile = resolve(company)
                self.assertEqual(profile.id, company)
                self.assertTrue(profile.domains)
                self.assertTrue(profile.seeds)
            self.assertEqual(resolve('Britannia Industries').id, 'britannia')

    def test_explicit_local_source_registration_still_overrides_defaults(self):
        custom = {
            'id':'britannia', 'legal_name':'Britannia Industries Limited',
            'business_model':'fmcg', 'domains':['britannia.co.in'],
            'seeds':['https://www.britannia.co.in/investors/'], 'peers':['hul'],
        }
        with patch('backend.storage.rows', return_value=[{'profile_json':json.dumps(custom)}]):
            self.assertEqual(profiles()['britannia'].seeds, custom['seeds'])
            self.assertEqual(resolve('britannia').peers, ['hul'])
