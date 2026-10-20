"""Small structured-output benchmark. Uses the same persisted call budget as runs."""
import asyncio
import json
from backend import storage, research
from backend.model import generate, ModelUnavailable


async def main():
    storage.initialize()
    run_id = research.create_run(research.RunRequest(company='hul', refresh=False))
    report = research.base_report(storage.rows('SELECT * FROM research_runs WHERE id=?', (run_id,))[0], research.resolve('hul'))
    try:
        result = await generate(run_id, 'extractor', {'passages': []}, research.Extracted)
        print(json.dumps({'structured_extraction_schema': 'passed', 'facts': len(result.facts)}))
    except ModelUnavailable as exc:
        report['limitations'].append(str(exc))
        print(json.dumps({'structured_extraction_schema': 'failed', 'reason': str(exc)}))
    finally:
        research.finish(run_id, report)


if __name__ == '__main__':
    asyncio.run(main())
