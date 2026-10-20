import asyncio
import json
from pathlib import Path
from uuid import uuid4
from pydantic import BaseModel, ConfigDict, Field
from backend import storage, model

class CaseReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    risks:list[str]=Field(max_length=8)
    inconsistencies:list[str]=Field(max_length=8)
    research_gaps:list[str]=Field(max_length=8)

async def main():
    storage.initialize()
    target=storage.PROJECT_DIR/'outputs/britannia-source-review'
    context={'case':json.loads((storage.PROJECT_DIR/'config/company_cases/britannia.json').read_text()),'evidence':[]}
    for key,pages in [('83b4e4ac30664191',[132,133,134,146,154]),('706ef2b6f0d3d58a',[5,6,7,14])]:
        doc=json.loads((target/(key+'.json')).read_text(encoding='utf-8'))
        context['evidence'].extend({'file':doc['file'],'page':p,'text':doc['pages'][p-1]['text']} for p in pages)
    run_id=uuid4().hex
    with storage.database() as db:
        db.execute('INSERT INTO research_runs(id,company,created_at,updated_at,evidence_cutoff,status,stage,request_json) VALUES(?,?,?,?,?,?,?,?)',
                   (run_id,'britannia',storage.now(),storage.now(),storage.today_ist().isoformat(),'running','excel_case_review',json.dumps({'purpose':'review conditional Excel case','company':'britannia'})))
    try:
        result=await model.generate(run_id,'case-review',context,CaseReview)
        review={'run_id':run_id,'status':'review completed','review_is_verified_facts':False,'review':result.model_dump()}
    except model.ModelUnavailable as exc:
        review={'run_id':run_id,'status':'unavailable','reason':str(exc),'review_is_verified_facts':False}
    (target/'gemini-review.json').write_text(json.dumps(review,indent=2),encoding='utf-8')
    report={'company':'Britannia Industries Limited','status':'Partial valuation case review',
        'evidence_strength':{'rating':'conditional','reasons':['Five years of consolidated statements reconciled; forecast assumptions and interim bridge remain estimates.']},
        'evidence_cutoff':storage.today_ist().isoformat(),'model_calls':len(storage.rows('SELECT model_calls FROM research_runs WHERE id=?',(run_id,))) and storage.rows('SELECT model_calls FROM research_runs WHERE id=?',(run_id,))[0]['model_calls'],
        'discovery':None,'candidate_discovery':None,'significance':[{'text':'Excel model prepared from the supplied Britannia source folder. Conditional scenarios are separate from verified historical facts.','citations':[]}],
        'calculations':[],'timeline':[],'counterargument':{'text':'Discount rates, interim cash balances and selected multiples require further validation. A scenario valuation is not a confirmed mispricing discovery.','citations':[]},
        'falsification_condition':'Refresh actual interim balances, measured capital costs and comparable multiples; reassess the valuation.',
        'limitations':['Gemini review is a critique of supplied evidence, not an independent data source.',review['status'],'See the Excel Research and Assumptions sheets for case details.'],
        'novelty':'Not established','sources':[],'valuation':[],'case_review':review}
    with storage.database() as db:
        db.execute('UPDATE research_runs SET status=?,stage=?,updated_at=?,report_json=? WHERE id=?',('partial','excel_case_review_finished',storage.now(),json.dumps(report),run_id))
    print(json.dumps(review,indent=2))

if __name__=='__main__':
    asyncio.run(main())
