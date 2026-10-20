import argparse
import asyncio
import json
from backend import storage
from backend.excel_engine import export_company

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('company', help='Company slug, e.g. hul. Reads only the configured new source library.')
    args = parser.parse_args()
    storage.initialize()
    print(json.dumps(asyncio.run(export_company(args.company)), indent=2))
