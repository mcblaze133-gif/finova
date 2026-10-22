"""Conditional HTTP and parser caches. Cached content alone never proves freshness."""
import hashlib
import json
import os
from pathlib import Path
from uuid import uuid4
from backend import storage


def root():
    # Follow the selected database, including isolated tests and recovery copies.
    return storage.DB_PATH.parent / 'source-cache'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid4().hex+'.tmp')
    try:
        temporary.write_bytes(data)
        os.replace(temporary,path)
    finally:
        temporary.unlink(missing_ok=True)


def index(url):
    return root()/'http'/(digest(url.encode())+'.json')


def load(url, limit):
    try:
        if index(url).stat().st_size>32_000:
            return None
        item=json.loads(index(url).read_text(encoding='utf-8'))
        sha=item['sha256']
        if item['url']!=url or not isinstance(sha,str) or len(sha)!=64 or any(c not in '0123456789abcdef' for c in sha):
            return None
        if not isinstance(item.get('content_type'),str):
            return None
        path=root()/'bodies'/sha
        if path.stat().st_size>limit:
            return None
        data=path.read_bytes()
        if digest(data)!=sha:
            return None
        return {**item,'data':data}
    except (OSError,ValueError,KeyError,TypeError):
        return None


def validators(item):
    result={}
    for field,header in [('etag','If-None-Match'),('last_modified','If-Modified-Since')]:
        value=item.get(field) if item else None
        if isinstance(value,str) and 0<len(value)<=2048 and '\r' not in value and '\n' not in value:
            result[header]=value
    return result


def store(url,data,content_type,headers):
    policy=headers.get('cache-control','').casefold()
    if 'no-store' in policy or 'private' in policy or headers.get('vary','').strip()=='*':
        index(url).unlink(missing_ok=True)
        return
    item={'url':url,'sha256':digest(data),'content_type':content_type,
          'etag':headers.get('etag'),'last_modified':headers.get('last-modified'),
          'checked_at':storage.now()}
    if not validators(item):
        index(url).unlink(missing_ok=True)
        return
    atomic(root()/'bodies'/item['sha256'],data)
    atomic(index(url),json.dumps(item).encode())


def revalidated(url,item,headers):
    # Only called after a real HTTP 304; no stale-on-error path exists.
    store(url,item['data'],item['content_type'],{
        'etag':headers.get('etag',item.get('etag')),
        'last-modified':headers.get('last-modified',item.get('last_modified')),
        'cache-control':headers.get('cache-control',''), 'vary':headers.get('vary',''),
    })
