"""Exercise the local HTTP service; print status only, never credentials."""
import argparse
import asyncio
import json
import httpx


async def main(company, cached=False):
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8000', timeout=15, trust_env=False) as client:
        health = await client.get('/health')
        health.raise_for_status()
        response = await client.post('/runs', json={'company': company, 'max_documents': 2, 'refresh': not cached})
        response.raise_for_status()
        run_id = response.json()['run_id']
        print(json.dumps({'run_id': run_id, 'status': 'started'}), flush=True)
        previous = None
        for _ in range(180):
            await asyncio.sleep(2)
            status = (await client.get('/runs/' + run_id)).json()
            stage = (status['status'], status['stage'], status['model_calls'])
            if stage != previous:
                print(json.dumps({'status': stage[0], 'stage': stage[1], 'model_calls': stage[2]}), flush=True)
                previous = stage
            if status['status'] not in ('queued', 'running'):
                report = (await client.get('/runs/' + run_id + '/report')).json()
                print(json.dumps({'run_id': run_id, 'status': report['status'],
                                  'documents': len(report['sources']), 'calculations': len(report['calculations']),
                                  'fact_checks': len(report.get('fact_checks', [])),
                                  'limitations': report['limitations']}), flush=True)
                return
        raise RuntimeError('Polling timeout.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('company', choices=['hul', 'trent', 'nestle-india', 'itc', 'tata-consumer', 'titan'])
    parser.add_argument('--cached', action='store_true')
    args = parser.parse_args()
    asyncio.run(main(args.company, args.cached))
