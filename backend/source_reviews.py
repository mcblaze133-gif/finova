"""Explicit reviewed documentary comparisons; not economic discovery attestations."""
import json
from backend import storage,peer_valuation


def build(company):
    path=storage.PROJECT_DIR/'data'/'source-reviews.json'
    if not path.exists():return []
    reviews=json.loads(path.read_text(encoding='utf-8')).get(company,[])
    return [{**item,'sources':[peer_valuation.evidence(ref) for ref in item['evidence']]}
            for item in reviews]
