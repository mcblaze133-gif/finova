"""Retain image-only statement pages using existing source-verified records.

This is a labelled record index, never OCR, a complete page transcription, or
new financial verification. Original PDFs and existing extracted text are intact.
"""
import json
import re
from collections import defaultdict
from pypdf import PdfReader
from backend import storage,library

PREFIX='Reviewed financial record index for a scanned PDF page. NOT OCR and NOT a verbatim page transcription. Only previously source-verified records are listed. Consult the original page image for complete context.'

def ensure(company):
    from backend.evidence_packs import digest_file
    root=library.root_folder();groups=defaultdict(list)
    for record in library.company_records(company):
        if record.review_status=='source_verified' and record.source_sha256 and record.source_quote:
            for page in map(int,re.findall(r'\d+',record.source_page)):
                groups[(record.source_file,record.source_sha256,page)].append(record)
    checked={};inserted=[]
    for (relative,digest,page),records in groups.items():
        docs=storage.rows('SELECT id,local_path FROM documents WHERE company=? AND sha256=?',(company,digest))
        if not docs:continue
        existing=storage.rows('SELECT id,text FROM passages WHERE document_id=? AND pdf_page=?',(docs[0]['id'],page))
        if existing and not existing[0]['text'].startswith(PREFIX):continue
        source=(root/relative).resolve()
        if not source.is_relative_to(root) or not source.is_file():continue
        key=(relative,digest)
        if key not in checked:
            if digest_file(source)!=digest:continue
            archive=(storage.PROJECT_DIR/docs[0]['local_path']).resolve()
            if not archive.is_relative_to((storage.DATA_DIR/'raw').resolve()) or digest_file(archive)!=digest:continue
            checked[key]=len(PdfReader(archive).pages)
        if not 1<=page<=checked[key]:raise ValueError('A reviewed record references a non-existent PDF page.')
        payload=[{k:r.model_dump(mode='json')[k] for k in ('metric','value','unit','period_start','period_end','accounting_scope','operations_scope','definition','source_quote','review_note')} for r in records]
        text=PREFIX+'\n'+json.dumps(payload,ensure_ascii=False,indent=2)
        with storage.database() as db:
            if existing:
                changed=db.execute('UPDATE passages SET text=? WHERE id=? AND text!=?',(text,existing[0]['id'],text)).rowcount
            else:
                changed=db.execute('INSERT OR IGNORE INTO passages(document_id,pdf_page,text) VALUES(?,?,?)',(docs[0]['id'],page,text)).rowcount
        if changed:inserted.append({'file':relative,'page':page,'document_id':docs[0]['id'],'records':len(records),'representation':'reviewed record index, not OCR'})
    return inserted
