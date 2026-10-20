"""Refresh local pack plus bounded live company, market and geopolitical research."""
import argparse
import asyncio
import json
from backend import storage, company_updates, model

async def main(company, extra_free_calls=False):
    run_id, created = company_updates.create(company)
    print(json.dumps({'refresh_id':run_id,'started':created}), flush=True)
    if created:
        if extra_free_calls:
            model.grant_two_calls(run_id, 'User explicitly approved exactly two additional free-tier calls for live search and impact assessment on 2026-10-18.')
        result = await company_updates.execute(run_id)
        print(json.dumps({'status':result['status'], 'events':len(result['events']),
                          'news_leads':len(result.get('news_leads', [])), 'feed_coverage':result.get('feed_coverage', []),
                          'limitations':result['limitations'], 'queries':result.get('queries',[])}, indent=2))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('company')
    parser.add_argument('--extra-free-calls', action='store_true', help='Requires explicit operator approval for a one-time two-call exception; never enables billing.')
    args = parser.parse_args()
    storage.initialize()
    asyncio.run(main(args.company, args.extra_free_calls))
