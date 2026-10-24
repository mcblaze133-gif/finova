"""Refresh registered public originals; retrieval is not factual verification."""
import asyncio
import json
import hashlib
import re
from datetime import date
from urllib.parse import urlsplit
from backend import documents,storage


def reviewed_pages(raw,url):
    """A visually reviewed transcript is usable only for its exact source bytes."""
    digest=hashlib.sha256(raw).hexdigest()
    path=storage.DATA_DIR/'reviewed-transcripts'/(digest+'.json')
    if not path.exists():return None
    record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('sha256')!=digest or record.get('url')!=url or record.get('method')!='manual-visual-transcription':
        raise ValueError('Reviewed transcript identity mismatch.')
    pages=record.get('pages')
    if not isinstance(pages,list) or not 1<=len(pages)<=documents.MAX_PAGES or not all(isinstance(p,str) for p in pages) or sum(map(len,pages))>documents.MAX_TEXT:
        raise ValueError('Reviewed transcript exceeds document limits.')
    text_digest=hashlib.sha256(json.dumps(pages,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
    if record.get('pages_sha256')!=text_digest:
        raise ValueError('Reviewed transcript text changed after its recorded review.')
    return pages


def registry(company):
    path=storage.PROJECT_DIR/'config/research_sources.json'
    data=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return data.get(company,[])[:4]


async def refresh(company,cutoff):
    cutoff=date.fromisoformat(str(cutoff))
    result={'checked_at':storage.now(),'sources':[],
            'meaning':'Original retrieval and file integrity checked. External credit opinions may rely on issuer data and are not independent verification of equity value.'}
    async def one(item):
        row={k:item[k] for k in ('url','title','publication_date','publisher','role')}
        if date.fromisoformat(item['publication_date'])>cutoff:
            return row|{'status':'excluded_after_cutoff'}
        fetcher=documents.Fetcher([urlsplit(item['url']).hostname])
        try:
            async with asyncio.timeout(30):
                raw,kind,url=await fetcher.fetch(item['url'])
                pages=reviewed_pages(raw,url) if item.get('reviewed_transcript') else None
                if item.get('reviewed_transcript') and pages is None:
                    raise ValueError('Changed scanned source requires a new visual transcription review.')
                kwargs={'extracted_pages':pages,'extraction_method':'manual-visual-transcription'} if pages else {}
                doc_id=await asyncio.to_thread(documents.save_document,company,url,item['title'],raw,kind,item['publication_date'],**kwargs)
            return row|{'status':'original_read','document_id':doc_id,'receipts':fetcher.receipts}
        except Exception as exc:
            # A failed live refresh never promotes an older archive as freshly read.
            return row|{'status':'unavailable','reason':type(exc).__name__}
    result['sources']=await asyncio.gather(*(one(item) for item in registry(company)))
    return result


def passages(refresh_result,query,limit=6):
    """Select exact source slices, retaining publication and publisher identity."""
    terms=set(re.findall(r'[a-z]{4,}',query.casefold()))
    ranked=[]
    for source in refresh_result.get('sources',[]):
        if source.get('status')!='original_read':continue
        rows=storage.rows('SELECT p.id,p.document_id,p.pdf_page,p.text,d.company,d.title,d.original_url,d.publication_date,d.sha256 FROM passages p JOIN documents d ON d.id=p.document_id WHERE d.id=?',(source['document_id'],))
        for row in rows:
            matches=[m for m in re.finditer(r'\b[a-z]{4,}\b',row['text'].casefold()) if m.group() in terms]
            if not matches:continue
            best=max(matches,key=lambda m:sum(m.start()<=x.start()<m.start()+2600 for x in matches))
            start=max(0,best.start()-180)
            row['text']=row['text'][start:start+3300]
            row['source_role']=source['role'];row['publisher']=source['publisher']
            row['retrieval_checked_at']=refresh_result['checked_at']
            ranked.append((len(matches),row))
    return [row for _,row in sorted(ranked,key=lambda pair:pair[0],reverse=True)[:limit]]
