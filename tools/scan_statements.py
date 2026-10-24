"""Scan archived uploaded annual statements. Never approve figures or call models."""
import argparse
import json
from backend import storage,statement_intake,verification
from backend.companies import resolve

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('company');args=parser.parse_args()
    storage.initialize();company=resolve(args.company).id
    result=statement_intake.scan(company)
    items=statement_intake.candidates(company)
    result.update(company=company,pending=sum(c['status']=='pending' for c in items),
                  automatically_approved=0,model_calls_added=0)
    target=storage.PROJECT_DIR/'reports'/f'{company}-statement-intake.json'
    target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
