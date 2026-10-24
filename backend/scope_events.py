"""Reviewed source inputs for ownership/scope changes, not company-specific code.

An event is usable only while its archived file hash and quoted passage match.
This conservative guard withholds unreconciled current-tense ownership claims.
"""
import json
import re
from pathlib import Path
from backend import storage
from backend.evidence_packs import digest_file
from backend.research import normalized


class ScopeEvidenceError(ValueError):pass


def load(company):
    path=storage.PROJECT_DIR/'data/scope-events.json'
    if not path.exists():return []
    try:
        entries=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError) as exc:
        raise ScopeEvidenceError('Reviewed scope-change registry cannot be read; ownership checks did not complete.') from exc
    if not isinstance(entries,list):raise ScopeEvidenceError('Invalid reviewed scope-change registry.')
    result=[]
    for event in entries:
        if event['company_id']!=company:continue
        rows=storage.rows('SELECT p.id,p.document_id,p.pdf_page,p.text,d.company,d.title,d.original_url,d.publication_date,d.sha256,d.local_path FROM passages p JOIN documents d ON d.id=p.document_id WHERE p.id=? AND d.company=?',(event['passage_id'],company))
        if not rows:raise ScopeEvidenceError('Reviewed scope-change evidence is missing.')
        row=rows[0];source=(storage.PROJECT_DIR/row['local_path']).resolve()
        if (not source.is_relative_to((storage.PROJECT_DIR/'data/raw').resolve()) or not source.is_file()
                or row['sha256']!=event['source_sha256'] or digest_file(source)!=event['source_sha256']
                or not event.get('quote') or normalized(event['quote']) not in normalized(row['text'])):
            raise ScopeEvidenceError('Reviewed scope-change evidence no longer matches its archived source.')
        result.append(event|{'passage':dict(row,text=event['quote'])})
    return result


def check(text,events,at_date=None):
    value=normalized(text)
    for event in events:
        if at_date and str(at_date)<event['observed_date']:continue
        if not any(normalized(alias) in value for alias in event['aliases']):continue
        # A qualified relationship or explicitly historical statement can be
        # reviewed normally. This is a withholding rule, not truth attestation.
        if any(re.search(r'\b'+re.escape(word)+r'\b',value) for word in event['required_qualifiers']):continue
        raise ValueError('Ownership/reporting-scope attribution needs reconciliation with reviewed event: '+event['label'])


def filter_research(raw,events):
    withheld=[]
    for key in ('discovery','candidate_discovery','counterargument'):
        statement=raw.get(key)
        if not isinstance(statement,dict):continue
        try:check(statement.get('text',''),events)
        except ValueError as exc:
            raw[key]=None;withheld.append({'field':key,'reason':str(exc)})
            raw.setdefault('discovery_checks',{})['admitted']=False
    for key in ('significance','timeline'):
        valid=[]
        for statement in raw.get(key,[]):
            try:check(statement.get('text',''),events,statement.get('date'));valid.append(statement)
            except ValueError as exc:withheld.append({'field':key,'reason':str(exc)})
        if key in raw:raw[key]=valid
    for section in raw.get('sector_sections',[]):
        valid=[]
        for statement in section.get('statements',[]):
            try:check(statement.get('text',''),events);valid.append(statement)
            except ValueError as exc:withheld.append({'field':section['topic'],'reason':str(exc)})
        section['statements']=valid
    raw['sector_sections']=[s for s in raw.get('sector_sections',[]) if s.get('statements')]
    raw['scope_validation']={'events':[{'label':e['label'],'observed_date':e['observed_date'],
                                      'document_id':e['passage']['document_id'],'page':e['passage']['pdf_page']} for e in events],
                             'withheld':withheld,'meaning':'Reviewed ownership changes constrain narrative claims. They are not a live ownership verification or an automatic change to financial assumptions.'}
