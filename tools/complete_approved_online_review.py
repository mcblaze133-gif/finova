"""Complete an already approved run using its remaining scoped call allowance."""
import argparse
import asyncio
import json
from backend import storage, company_updates

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_id')
    args = parser.parse_args()
    storage.initialize()
    grant = storage.rows('SELECT remaining_calls FROM model_call_grants WHERE run_id=? AND utc_day=?', (args.run_id,storage.now()[:10]))
    if not grant or grant[0]['remaining_calls'] != 1:
        raise SystemExit('This run does not have exactly one remaining approved call.')
    result = asyncio.run(company_updates.execute(args.run_id))
    print(json.dumps({'refresh_id':args.run_id,'status':result['status'],'events':len(result['events']),
                      'limitations':result['limitations']}, indent=2))
