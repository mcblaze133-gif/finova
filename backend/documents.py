"""Bounded public-source ingestion. No arbitrary files, private URLs or browser cookies."""
import asyncio
import hashlib
import io
import ipaddress
import json
import re
import socket
from html.parser import HTMLParser
from urllib.parse import urlsplit, urljoin, urldefrag
from urllib.robotparser import RobotFileParser

import httpx
from pypdf import PdfReader
from backend import storage

USER_AGENT = 'SignalAIResearch/0.3'
MAX_BYTES = 40 * 1024 * 1024
MAX_PAGES = 600
MAX_TEXT = 3_000_000


def allowed_url(url, domains):
    parsed = urlsplit(url)
    host = (parsed.hostname or '').lower().rstrip('.')
    if (parsed.scheme != 'https' or not host or parsed.username or parsed.password
            or parsed.port not in (None, 443)):
        raise ValueError('Only public HTTPS sources on port 443 are allowed.')
    if not any(host == d or host.endswith('.' + d) for d in domains):
        raise ValueError('Source host is outside the registered company domains.')
    if len(url) > 2048:
        raise ValueError('Source URL is too long.')
    return urldefrag(url)[0]


async def public_host(url):
    host = urlsplit(url).hostname
    addresses = await asyncio.to_thread(socket.getaddrinfo, host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Private and local network addresses are blocked.')


class HTMLText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text, self.links, self.hidden = [], [], 0
        self.anchor = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden += 1
        if tag in ('p', 'br', 'div', 'tr', 'h1', 'h2', 'h3', 'li'):
            self.text.append('\n')
        if tag == 'a':
            self.anchor = [attrs.get('href', ''), '']

    def handle_endtag(self, tag):
        if tag in ('script', 'style', 'noscript', 'svg'):
            self.hidden = max(0, self.hidden - 1)
        if tag == 'a' and self.anchor:
            self.links.append(tuple(self.anchor))
            self.anchor = None

    def handle_data(self, data):
        if not self.hidden:
            self.text.append(data + ' ')
            if self.anchor:
                self.anchor[1] += data


class Fetcher:
    def __init__(self, domains):
        self.domains = domains
        self.robots = {}
        self.requests = 0

    async def raw(self, url, limit=MAX_BYTES, *, access_policy=None):
        initial_host = urlsplit(url).hostname
        for _ in range(4):
            url = allowed_url(url, self.domains)
            if urlsplit(url).hostname != initial_host:
                raise ValueError('Cross-origin redirect requires a separately registered source URL.')
            if access_policy is not None and not access_policy.can_fetch(USER_AGENT,url):
                raise ValueError('Source disallows this automated retrieval in robots.txt.')
            if access_policy is not None and _:
                await asyncio.sleep(access_policy.crawl_delay(USER_AGENT) or 1)
            await public_host(url)
            self.requests += 1
            if self.requests > 45:
                raise ValueError('Source request budget exhausted.')
            # No proxy environment or credentials inherited by source requests.
            async with httpx.AsyncClient(timeout=httpx.Timeout(25, connect=10), trust_env=False,
                                         follow_redirects=False, headers={'User-Agent': USER_AGENT}) as client:
                async with client.stream('GET', url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    if response.status_code != 200:
                        raise ValueError(f'Source returned HTTP {response.status_code}.')
                    data = bytearray()
                    async for block in response.aiter_bytes():
                        data.extend(block)
                        if len(data) > limit:
                            raise ValueError('Source exceeds download size limit.')
                    return bytes(data), response.headers.get('content-type', ''), url
        raise ValueError('Too many source redirects.')

    async def fetch(self, url):
        url = allowed_url(url, self.domains)
        origin = '{0.scheme}://{0.netloc}'.format(urlsplit(url))
        if origin not in self.robots:
            try:
                data, _, _ = await self.raw(origin + '/robots.txt', 256_000)
                parser = RobotFileParser()
                parser.parse(data.decode('utf-8', 'replace').splitlines())
            except ValueError as exc:
                # An explicit 404 means no robots file; all other failures stop access.
                if 'HTTP 404' not in str(exc):
                    raise ValueError('Cannot establish automated source access policy.') from None
                parser = RobotFileParser()
                parser.parse([])
            self.robots[origin] = parser
        parser = self.robots[origin]
        if not parser.can_fetch(USER_AGENT, url):
            raise ValueError('Source disallows this automated retrieval in robots.txt.')
        delay = parser.crawl_delay(USER_AGENT) or 1
        if delay > 10:
            raise ValueError('Source crawl delay exceeds run budget.')
        await asyncio.sleep(delay)
        result = await self.raw(url, access_policy=parser)
        # Redirect destinations must have their own access policy checked before
        # storing or parsing content. Cross-origin redirects are rejected here.
        if urlsplit(result[2]).netloc != urlsplit(url).netloc:
            raise ValueError('Cross-origin redirect requires a separately registered source URL.')
        return result


def extract(data, content_type):
    if data.startswith(b'%PDF-'):
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise ValueError('Encrypted PDF is not supported.')
        if len(reader.pages) > MAX_PAGES:
            raise ValueError('PDF exceeds page limit.')
        pages, length = [], 0
        for page in reader.pages:
            content = page.get_contents()
            if content and len(content.get_data()) > 10_000_000:
                raise ValueError('PDF page exceeds extraction limit.')
            text = page.extract_text(extraction_mode='layout') or ''
            length += len(text)
            if length > MAX_TEXT:
                raise ValueError('PDF exceeds extracted text limit.')
            pages.append(text)
        if sum(len(p.strip()) for p in pages) < 80:
            raise ValueError('No usable PDF text. OCR is unavailable; no facts were invented.')
        return pages, []
    if 'html' not in content_type.lower():
        raise ValueError('Only PDF and HTML sources are supported.')
    parser = HTMLText()
    parser.feed(data.decode('utf-8', 'replace'))
    text = re.sub(r'[ \t]+', ' ', ''.join(parser.text))
    if len(text) > MAX_TEXT:
        raise ValueError('HTML exceeds extracted text limit.')
    if len(text.strip()) < 80:
        raise ValueError('Source has no usable text; it may require JavaScript.')
    return [text], parser.links


def save_document(company, url, title, data, content_type, publication_date=None, *, extracted_pages=None):
    if extracted_pages is None:
        pages, _ = extract(data, content_type)
    else:
        # Used only by bounded local-PDF fallback, never taken from API inputs.
        pages = extracted_pages
        if not pages or len(pages) > MAX_PAGES or sum(len(p) for p in pages) > MAX_TEXT:
            raise ValueError('Local PDF fallback exceeds extraction limits.')
        if sum(len(p.strip()) for p in pages) < 80:
            raise ValueError('No usable PDF text. OCR/manual review required.')
    digest = hashlib.sha256(data).hexdigest()
    suffix = '.pdf' if data.startswith(b'%PDF-') else '.html'
    path = storage.DATA_DIR / 'raw' / (digest + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Content addressed files can be safely reused after DB rollback/re-ingestion.
    if not path.exists():
        path.write_bytes(data)
    with storage.database() as db:
        db.execute('INSERT OR IGNORE INTO documents(company,title,original_url,publication_date,retrieved_at,sha256,local_path) VALUES(?,?,?,?,?,?,?)',
                   (company, title[:300], url, publication_date, storage.now(), digest, str(path.relative_to(storage.PROJECT_DIR))))
        document_id = db.execute('SELECT id FROM documents WHERE company=? AND sha256=?', (company, digest)).fetchone()[0]
        db.execute('INSERT OR IGNORE INTO document_sources(document_id,url,source_family,retrieved_at) VALUES(?,?,?,?)',
                   (document_id, url, company, storage.now()))
        db.executemany('INSERT OR IGNORE INTO passages(document_id,pdf_page,text) VALUES(?,?,?)',
                       [(document_id, index, text) for index, text in enumerate(pages, 1) if text.strip()])
    processed = storage.DATA_DIR / 'processed'
    processed.mkdir(parents=True, exist_ok=True)
    (processed / (digest + '.json')).write_text(json.dumps({'sha256': digest, 'pages': pages,
        'extraction_method': 'local-bounded-fallback' if extracted_pages is not None else 'pypdf-layout'}, ensure_ascii=False), encoding='utf-8')
    return document_id


async def ingest(profile, url, title='Public disclosure', publication_date=None):
    fetcher = Fetcher(profile.domains)
    data, kind, original = await fetcher.fetch(url)
    return await asyncio.to_thread(save_document, profile.id, original, title, data, kind, publication_date)


def rank_link(link):
    text = ' '.join(link).lower()
    score = sum(weight for word, weight in (('annual', 2), ('result', 6), ('financial', 4), ('statement', 4), ('quarter', 3), ('presentation', -3), ('transcript', 1)) if word in text)
    score += 2 if '.pdf' in link[0].lower() else 0
    years = re.findall(r'20[12]\d', text)
    years += ['20' + year for year in re.findall(r"\b(?:jq|mq|dq|sq|fy)[\s'’_-]*(\d{2})(?!\d)", text)]
    return (max(years, default='0000'), score)


async def discover(profile, limit=4, log=None):
    fetcher = Fetcher(profile.domains)
    candidates, ids, errors = {}, [], []
    for seed in profile.seeds[:2]:
        try:
            data, kind, original = await fetcher.fetch(seed)
            _, links = extract(data, kind)
            for href, title in links:
                try:
                    url = allowed_url(urljoin(original, href), profile.domains)
                except ValueError:
                    continue
                if rank_link((url, title))[1] >= 2:
                    candidates[url] = title.strip() or 'Public financial disclosure'
            if data.startswith(b'%PDF-') and len(ids) < limit:
                ids.append(await asyncio.to_thread(save_document, profile.id, original, 'Seed disclosure', data, kind))
        except (ValueError, httpx.HTTPError, OSError):
            errors.append({'url': seed, 'reason': 'Archive unavailable, unsupported or access restricted.'})
    ranked = sorted(candidates.items(), key=rank_link, reverse=True)
    # Bound archive traversal: follow at most two relevant HTML archive pages.
    for url, title in [x for x in ranked if '.pdf' not in x[0].lower() and x[0] not in profile.seeds][:2]:
        try:
            data, kind, original = await fetcher.fetch(url)
            _, links = extract(data, kind)
            for href, label in links:
                target = urljoin(original, href)
                if '.pdf' in target.lower():
                    try:
                        candidates[allowed_url(target, profile.domains)] = label or title
                    except ValueError:
                        pass
        except (ValueError, httpx.HTTPError, OSError):
            errors.append({'url': url, 'reason': 'Linked archive could not be read.'})
    pdfs = sorted((x for x in candidates.items() if '.pdf' in x[0].lower()), key=rank_link, reverse=True)
    for url, title in pdfs[:max(0, limit - len(ids))]:
        try:
            data, kind, original = await fetcher.fetch(url)
            ids.append(await asyncio.to_thread(save_document, profile.id, original, title, data, kind))
            if log:
                log({'url': original, 'status': 'read'})
        except Exception:
            errors.append({'url': url, 'reason': 'Document unavailable, restricted, oversized or extraction failed.'})
    return {'document_ids': list(dict.fromkeys(ids)), 'errors': errors,
            'coverage': 'Official seeded archives only; broad web search and independent novelty search unavailable.',
            'requests': fetcher.requests}


def search(company, query, limit=12, cutoff=None):
    terms = list(dict.fromkeys(re.findall(r'[\w-]{3,40}', query.lower())))[:10]
    if not terms:
        return []
    conditions = ' OR '.join('lower(p.text) LIKE ?' for _ in terms)
    params = [company, *['%' + t + '%' for t in terms]]
    date_filter = ''
    if cutoff:
        date_filter = ' AND d.publication_date IS NOT NULL AND d.publication_date<=?'
        params.append(cutoff)
    result = storage.rows(f'SELECT p.*,d.title,d.original_url,d.publication_date,d.sha256,d.company FROM passages p JOIN documents d ON d.id=p.document_id WHERE d.company=? AND ({conditions}){date_filter} ORDER BY d.publication_date DESC,p.id DESC LIMIT 120', params)
    def score(row):
        return sum(min(row['text'].lower().count(term), 10) for term in terms)
    return sorted(result, key=score, reverse=True)[:limit]
