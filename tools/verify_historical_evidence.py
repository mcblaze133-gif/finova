"""Check every selected PDF page against its archived original; no AI calls."""
import argparse
import json
from pypdf import PdfReader
from backend import storage,evidence_packs as packs,investigation,library
from tools.prepare_all_company_evidence import write_text
from tools.upgrade_historical_evidence import COMPANIES


def verify(company):
    manifest=packs.read_manifest(company)
    assert manifest['version']==packs.VERSION,'Historical pack not ready'
    root=packs.pack_root(company)
    assert packs._valid_artifacts(root,manifest['artifact_hashes']),'Changed derived artifact'
    rows,proof=investigation.prepared_passages(company)
    pages=json.loads((root/manifest['pages']).read_text(encoding='utf-8'))
    pdf=PdfReader(root/manifest['pdf'])
    assert len(pdf.pages)==len(pages)==len(rows)
    originals={}
    for index,page in enumerate(pages):
        sha=page['source_sha256']
        if sha not in originals:
            path=storage.DATA_DIR/'raw'/f'{sha}.pdf'
            assert packs.digest_file(path)==sha,'Archived source changed'
            originals[sha]=PdfReader(path)
        original=originals[sha].pages[page['original_page']-1]
        actual=pdf.pages[index]
        assert list(actual.mediabox)==list(original.mediabox),'Page size changed'
        assert actual.get_contents().get_data()==original.get_contents().get_data(),f'Printed page content changed at {index+1}'
    assert all(d['selected_original_pages'] or d.get('duplicate_of') for d in manifest['source_index']),'Readable source silently excluded'
    seed=investigation.search_prepared(rows,'revenue profit cash inventory volume margin guidance',12)
    source_folder=library.company_folder(company)/'SignalAI Evidence'
    published=json.loads((source_folder/'manifest.json').read_text(encoding='utf-8'))
    published_pdf=source_folder/published['version_folder']/'Valuation evidence.pdf'
    assert packs.digest_file(published_pdf)==manifest['artifact_hashes'][manifest['pdf']]
    return {'company':company,'verified_at':storage.now(),'signature':manifest['signature'],
            'selected_pages':len(pages),'every_printed_page_matches_original':True,
            'input_pdfs':manifest['input_files'],'readable_pdfs':manifest['source_files'],
            'unreadable_pdfs':manifest['unreadable_files'],
            'seed_period_hints_unverified':sorted({tuple(r['period_sort_hint_unverified']) for r in seed if r.get('period_sort_hint_unverified')}),
            'published_pdf':str(published_pdf),'model_calls':0,
            'limitation':'Source selection and copied-page integrity do not verify financial values or establish a discovery.'}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--company',action='append',choices=COMPANIES)
    args=parser.parse_args()
    results=[]
    for company in args.company or COMPANIES:
        result=verify(company);results.append(result)
        write_text(storage.PROJECT_DIR/'reports'/f'historical-verification-{company}.json',json.dumps(result,indent=2))
        print(json.dumps({'company':company,'verified_pages':result['selected_pages']}),flush=True)
    write_text(storage.PROJECT_DIR/'reports/historical-evidence-verification.json',json.dumps({'created_at':storage.now(),'companies':results},indent=2))


if __name__=='__main__':main()
