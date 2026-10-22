"""Measure two real official-source checks without a model request or fact import."""
import argparse
import asyncio
import json
from time import perf_counter
from pathlib import Path
from unittest.mock import patch
from backend import documents, storage
from backend.companies import resolve


async def main(company,url):
    profile=resolve(company)
    documents.allowed_url(url,profile.domains)
    rows=[];hashes=[]
    for attempt in range(2):
        fetcher=documents.Fetcher(profile.domains)
        started=perf_counter()
        async with asyncio.timeout(75):
            data,kind,final=await fetcher.fetch(url)
        fetched=perf_counter()
        with patch.object(documents,'extract',wraps=documents.extract) as parser:
            pages,_=await asyncio.to_thread(documents.extract_cached,data,kind)
            extractions=parser.call_count
        hashes.append(documents.hashlib.sha256(data).hexdigest())
        rows.append({'attempt':attempt+1,'url':final,'fetch_seconds':round(fetched-started,3),
                     'parse_seconds':round(perf_counter()-fetched,3),'pages':len(pages),
                     'parser_executions':extractions,'requests':fetcher.requests,
                     'freshness_receipts':fetcher.receipts})
    result={'company':company,'checks':rows,'content_unchanged':len(set(hashes))==1,
            'model_requests':0,'financial_facts_imported':0}
    target=storage.PROJECT_DIR/'reports/incremental-retrieval.json'
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('company');parser.add_argument('--url',required=True)
    args=parser.parse_args();asyncio.run(main(args.company,args.url))
