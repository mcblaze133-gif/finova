"""Archive user-supplied originals and searchable passages without inventing URLs."""
import argparse
import json
import logging
from backend import storage, library

def main(company):
    storage.initialize()
    # Font warnings were inspected during source preparation; the original PDFs
    # remain authoritative and finance acceptance is a separate reviewed step.
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    existing={row['relative_path'] for row in storage.rows('SELECT relative_path FROM library_documents WHERE company=?',(company,))}
    results=[]
    for file in library.inventory()['files']:
        relative=file['relative_path']
        if file['type']!='pdf' or relative.split('/')[0]!=company:continue
        if relative in existing:
            results.append({'file':relative,'status':'already cached'});continue
        result=library.import_pdf(company,relative)
        results.append({'file':relative,**result})
        print(json.dumps({'file':relative,'status':result['status']}),flush=True)
    target=storage.PROJECT_DIR/'outputs'/f'{company}-source-review'/'library-cache.json'
    target.write_text(json.dumps(results,indent=2),encoding='utf-8')
    print(json.dumps({'company':company,'local_pdfs':len(results),'original_urls_invented':False}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('company');main(parser.parse_args().company)
