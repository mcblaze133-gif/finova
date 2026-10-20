"""Retrieve public originals without consuming a model call."""
import argparse
import asyncio
import json
from backend import documents, storage
from backend.companies import resolve


async def main(company, limit):
    storage.initialize()
    result = await documents.discover(resolve(company), limit)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('company')
    parser.add_argument('--limit', type=int, default=2, choices=range(1, 7))
    args = parser.parse_args()
    asyncio.run(main(args.company, args.limit))
