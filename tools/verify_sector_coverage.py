"""Check all scoped companies without model requests or creating new reports."""
import json
from backend import storage, sector_status


def main():
    storage.initialize()
    data=sector_status.build()
    path=storage.PROJECT_DIR/'reports/sector-coverage.json'
    path.write_text(json.dumps(data,indent=2),encoding='utf-8')
    for row in data['companies']:
        print(row['company_id'],'delivery checks:',row['checks_passed'],
              'operating areas:',str(row.get('operating_complete',0))+'/'+str(row.get('operating_total',0)),
              'peer benchmark rows:',row.get('operating_benchmark_rows',0),
              'unresolved:',', '.join(row.get('unresolved_areas',[])))
    if not data['all_delivery_checks_passed']:raise SystemExit(1)


if __name__=='__main__':main()
