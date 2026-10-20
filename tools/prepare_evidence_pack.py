"""Create or reuse a local company evidence pack without model/API calls."""
import argparse
import json
from backend import storage, evidence_packs

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('company')
    parser.add_argument('--search')
    args = parser.parse_args()
    storage.initialize()
    result = evidence_packs.search(args.company, args.search) if args.search else evidence_packs.refresh(args.company)
    print(json.dumps({k: v for k, v in result.items() if k not in ('artifact_hashes','source_fingerprints')}, indent=2))
