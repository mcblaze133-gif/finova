"""Run each authorised company case with a new online check and Excel build."""
import asyncio
import json
from backend import storage, excel_engine

async def main():
    completed=[]
    for company in ('hul','nestle-india','itc','tata-consumer'):
        ready=excel_engine.valuation_readiness(company)
        if not ready['can_build']:
            raise ValueError(f'{company}: '+', '.join(ready['missing']))
        result=await excel_engine.export_company(company)
        completed.append({'company':company,**result})
        (storage.PROJECT_DIR/'reports/remaining-company-models.json').write_text(json.dumps(completed,indent=2),encoding='utf-8')
        print(json.dumps({'company':company,'export_id':result['export_id'],'status':result['status']}),flush=True)
        if result['status']!='exported':
            raise ValueError('Workbook did not pass authoring verification: '+company)

if __name__=='__main__':
    storage.initialize()
    asyncio.run(main())
