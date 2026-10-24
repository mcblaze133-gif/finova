"""Source locations, never company-specific conclusions or financial numbers."""
from pydantic import BaseModel, Field, ConfigDict


class Company(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(pattern=r'^[a-z0-9-]{2,60}$')
    legal_name: str = Field(min_length=2, max_length=160)
    business_model: str = Field(pattern=r'^(fmcg|retail|jewellery|diversified|platform|consumer)$')
    domains: list[str] = Field(min_length=1, max_length=8)
    seeds: list[str] = Field(min_length=1, max_length=8)
    peers: list[str] = Field(default_factory=list, max_length=4)


PROFILES = [
    Company(id='britannia', legal_name='Britannia Industries Limited', business_model='fmcg',
            domains=['britannia.co.in'],
            seeds=['https://www.britannia.co.in/investors/financial-performance/financial-results?tab=financial-performance']),
    Company(id='hul', legal_name='Hindustan Unilever Limited', business_model='fmcg',
            domains=['hul.co.in'], seeds=['https://www.hul.co.in/investors/results-and-presentations/quarterly-results-and-webcasts/', 'https://www.hul.co.in/investors/annual-reports-and-performance-highlights/annual-reports/'], peers=['nestle-india']),
    Company(id='trent', legal_name='Trent Limited', business_model='retail',
            domains=['trentlimited.com', 'docs.trent-tata.com', 'docs.trentlimited.com', 'cdn.shopify.com'],
            seeds=['https://trentlimited.com/pages/annual-reports', 'https://trentlimited.com/pages/financial-information']),
    Company(id='nestle-india', legal_name='Nestle India Limited', business_model='fmcg',
            domains=['nestle.in'], seeds=['https://www.nestle.in/investors/stockandfinancials/financialresults'], peers=['hul']),
    Company(id='itc', legal_name='ITC Limited', business_model='diversified',
            domains=['itcportal.com'], seeds=['https://itcportal.com/investors/quarterly-results.html'], peers=['hul']),
    Company(id='tata-consumer', legal_name='Tata Consumer Products Limited', business_model='fmcg',
            domains=['tataconsumer.com'], seeds=['https://www.tataconsumer.com/investors/investor-relations/results-and-presentation/consolidated-results'], peers=['nestle-india']),
    Company(id='titan', legal_name='Titan Company Limited', business_model='jewellery',
            domains=['titancompany.in'], seeds=['https://www.titancompany.in/investors/annual-reports']),
]


def profiles():
    from backend.storage import rows
    custom = [Company.model_validate_json(r['profile_json']) for r in rows('SELECT profile_json FROM companies')]
    return {p.id: p for p in [*PROFILES, *custom]}


def resolve(name):
    key = name.strip().casefold()
    aliases = {'hindustan unilever': 'hul', 'nestlé india': 'nestle-india',
               'nestle': 'nestle-india', 'tata consumer products': 'tata-consumer'}
    key = aliases.get(key, key)
    for profile in profiles().values():
        if key in (profile.id, profile.legal_name.casefold(), profile.legal_name.casefold().removesuffix(' limited')):
            return profile
    raise ValueError('Unknown company. Register its public investor sources with POST /companies first.')
