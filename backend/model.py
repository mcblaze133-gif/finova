"""One provider, bounded calls, sanitized failures, no paid fallback."""
import asyncio
import json
import hashlib
import httpx
from datetime import datetime,timezone,timedelta,time
from backend import storage
from backend.config import model_settings, ROOT


DAILY_REQUEST_LIMIT = 100


class ModelUnavailable(RuntimeError):
    def __init__(self,message,provider_status=None):
        super().__init__(message)
        self.provider_status=provider_status


def validated_response(role, schema, answer):
    if role == 'sector':
        from backend.sector_research import Assessment, QUERIES
        data=json.loads(answer)
        if not isinstance(data,dict) or not isinstance(data.get('assessments'),list) or len(data['assessments'])>9:
            return schema.model_validate_json(answer)
        accepted={};duplicates=set()
        for item in data['assessments']:
            try:
                value=Assessment.model_validate(item)
                if value.topic in accepted:duplicates.add(value.topic)
                else:accepted[value.topic]=value.model_dump(mode='json')
            except ValueError:
                continue
        for topic in duplicates:accepted.pop(topic,None)
        data={'assessments':[accepted.get(topic,{'topic':topic,'statements':[],'counterevidence':None,
              'investor_use':'This area requires a valid source-grounded assessment before use.',
              'gaps':['No usable source-supported assessment was returned for this area; it remains unresolved.']}) for topic in QUERIES]}
        return schema.model_validate(data)
    if role != 'updates':
        return schema.model_validate_json(answer)
    # A malformed proposed event must not discard independently valid siblings.
    # Never repair a citation, date, enum or invented value on the model's behalf.
    from backend.company_updates import Event
    data=json.loads(answer)
    if not isinstance(data,dict) or not isinstance(data.get('events'),list) or len(data['events'])>12:
        return schema.model_validate_json(answer)
    accepted=[]
    rejected=0
    for event in data['events']:
        try:
            accepted.append(Event.model_validate(event).model_dump(mode='json'))
        except ValueError:
            rejected+=1
    if rejected and isinstance(data.get('coverage_gaps'),list):
        data['events']=accepted
        data['coverage_gaps']=[f'{rejected} proposed event(s) rejected by the event schema; their claims were not accepted.']+data['coverage_gaps'][:11]
    return schema.model_validate(data)


def provider_schema(schema):
    """Use a small provider grammar; Pydantic enforces the full contract locally."""
    original = schema.model_json_schema()
    definitions = original.get('$defs', {})
    def convert(node):
        if isinstance(node, list):
            return [convert(item) for item in node]
        if not isinstance(node, dict):
            return node
        if '$ref' in node:
            return convert(definitions[node['$ref'].split('/')[-1]])
        result = {key: convert(value) for key, value in node.items()
                  if key in ('type', 'properties', 'items', 'required', 'anyOf', 'description')}
        # Enumerations become descriptions to avoid combinatorial grammar limits.
        if 'enum' in node:
            result['description'] = 'Allowed values: ' + ', '.join(map(str, node['enum']))
        if 'const' in node:
            result['description'] = 'Must be: ' + str(node['const'])
        if 'properties' in node:
            result['properties'] = {k: convert(v) for k, v in node['properties'].items()}
        return result
    return convert(original)


def _daily_calls(db, day):
    # Migrate older counters once per run. Historical call timestamps were not
    # recorded; retain their original UTC-day attribution conservatively.
    db.execute('CREATE TABLE IF NOT EXISTS model_call_ledger (run_id TEXT NOT NULL REFERENCES research_runs(id), utc_day TEXT NOT NULL, calls INTEGER NOT NULL CHECK(calls>=0), PRIMARY KEY(run_id,utc_day))')
    db.execute('''INSERT INTO model_call_ledger(run_id,utc_day,calls)
                  SELECT id,substr(created_at,1,10),model_calls FROM research_runs r
                  WHERE model_calls>0 AND NOT EXISTS
                  (SELECT 1 FROM model_call_ledger l WHERE l.run_id=r.id)''')
    return db.execute('SELECT COALESCE(SUM(calls),0) FROM model_call_ledger WHERE utc_day=?', (day,)).fetchone()[0]


def _daily_limit(db,day):
    table=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='model_daily_extensions'").fetchone()
    row=db.execute('SELECT extra_attempts,expires_at FROM model_daily_extensions WHERE utc_day=?',(day,)).fetchone() if table else None
    limit=DAILY_REQUEST_LIMIT
    timestamp=datetime.fromisoformat(storage.now())
    if row and timestamp<datetime.fromisoformat(row['expires_at']):
        limit+=row['extra_attempts']
    if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='model_recording_topups'").fetchone():
        for grant in db.execute('SELECT extra_attempts,expires_at FROM model_recording_topups WHERE utc_day=?',(day,)):
            if timestamp<datetime.fromisoformat(grant['expires_at']):limit+=grant['extra_attempts']
    return limit


def approve_recording_topup(approval_id, attempts, reason):
    """Operator-only, explicit approval; replaying the same approval never stacks."""
    if not approval_id or type(attempts) is not int or not 1<=attempts<=20 or len(reason.strip())<20:
        raise ValueError('A unique approval, 1–20 attempts and explicit approval reason are required.')
    storage.initialize()
    timestamp=storage.now()
    ist=timezone(timedelta(hours=5,minutes=30))
    expiry=datetime.combine(storage.today_ist()+timedelta(days=1),time.min,tzinfo=ist).astimezone(timezone.utc).isoformat()
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO model_recording_topups VALUES(?,?,?,?,?,?)',
                   (approval_id,timestamp[:10],attempts,timestamp,expiry,reason))
        return dict(db.execute('SELECT * FROM model_recording_topups WHERE approval_id=?',(approval_id,)).fetchone())


def approve_recording_allowance(reason):
    """Operator-only: explicit user approval, once, expires at local midnight."""
    if len(reason.strip())<20:raise ValueError('Record the explicit user approval.')
    storage.initialize()
    timestamp=storage.now()
    ist=timezone(timedelta(hours=5,minutes=30))
    expiry=datetime.combine(storage.today_ist()+timedelta(days=1),time.min,tzinfo=ist).astimezone(timezone.utc).isoformat()
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO model_daily_extensions VALUES(?,?,?,?,?)',(timestamp[:10],10,timestamp,expiry,reason))
        return dict(db.execute('SELECT * FROM model_daily_extensions WHERE utc_day=?',(timestamp[:10],)).fetchone())


def reserve_probe():
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        timestamp = storage.now()
        probes = db.execute('SELECT COUNT(*) FROM model_probes WHERE substr(created_at,1,10)=?', (timestamp[:10],)).fetchone()[0]
        calls = _daily_calls(db, timestamp[:10])
        if probes >= 3 or calls + probes >= _daily_limit(db,timestamp[:10]):
            raise ModelUnavailable('Local model test budget exhausted.')
        db.execute('INSERT INTO model_probes(created_at) VALUES(?)', (timestamp,))


def require_capacity(attempts=5):
    """Admission check only; actual attempts are still reserved individually."""
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        day=storage.now()[:10]
        used=_daily_calls(db,day)+db.execute('SELECT COUNT(*) FROM model_probes WHERE substr(created_at,1,10)=?',(day,)).fetchone()[0]
        limit=_daily_limit(db,day)
        if used+attempts>limit:
            raise ModelUnavailable(f'Today’s local free-tier allowance has {max(0,limit-used)} attempts left. A fresh investigation needs capacity for {attempts}. No previous report will be substituted.')


def reserve_call(run_id):
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        day = storage.now()[:10]
        calls = db.execute('SELECT model_calls FROM research_runs WHERE id=?', (run_id,)).fetchone()
        daily = _daily_calls(db, day)
        daily += db.execute('SELECT COUNT(*) FROM model_probes WHERE substr(created_at,1,10)=?', (day,)).fetchone()[0]
        if not calls or calls[0] >= 8:
            raise ModelUnavailable('Local model call budget exhausted. No fallback was called.')
        limit=_daily_limit(db,day)
        if daily >= limit:
            if limit>DAILY_REQUEST_LIMIT:
                raise ModelUnavailable('The approved recording allowance is exhausted. No fallback was called.')
            table = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='model_call_grants'").fetchone()
            grant = db.execute('SELECT remaining_calls FROM model_call_grants WHERE run_id=? AND utc_day=?',
                               (run_id, day)).fetchone() if table else None
            if not grant or grant[0] <= 0:
                raise ModelUnavailable('Local model call budget exhausted. No fallback was called.')
            db.execute('UPDATE model_call_grants SET remaining_calls=remaining_calls-1 WHERE run_id=?', (run_id,))
        db.execute('UPDATE research_runs SET model_calls=model_calls+1 WHERE id=?', (run_id,))
        db.execute('INSERT INTO model_call_ledger VALUES(?,?,1) ON CONFLICT(run_id,utc_day) DO UPDATE SET calls=calls+1', (run_id, day))


def grant_two_calls(run_id, reason):
    """Explicit operator approval only; at most two extra calls across this UTC day."""
    if len(reason.strip()) < 20:
        raise ValueError('Record the explicit approval reason.')
    with storage.database() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT COUNT(*) FROM model_call_grants WHERE utc_day=?', (storage.now()[:10],)).fetchone()[0]:
            raise ValueError('Today already has its two-call exception; no additional grant created.')
        db.execute('INSERT INTO model_call_grants VALUES(?,?,?,?,?)',
                   (run_id,storage.now()[:10],storage.now(),2,reason))


async def grounded_search(run_id, prompt):
    """Free-tier documented search model; no model switch or paid retry on failure."""
    try:
        key, _ = model_settings()
    except RuntimeError as exc:
        raise ModelUnavailable(str(exc)) from None
    reserve_call(run_id)
    storage.event(run_id, 'online_search', {'status': 'request started', 'model': 'gemini-2.5-flash-lite'})
    payload = {'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
               'tools': [{'google_search': {}}],
               'generationConfig': {'temperature': 0, 'maxOutputTokens': 5000}}
    try:
        async with httpx.AsyncClient(timeout=90, trust_env=False) as client:
            response = await client.post('https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent',
                                         headers={'x-goog-api-key': key}, json=payload)
    except httpx.RequestError:
        raise ModelUnavailable('Online search connection failed. Coverage is incomplete; no paid fallback.') from None
    if response.status_code != 200:
        raise ModelUnavailable(f'Online search returned HTTP {response.status_code}. No paid fallback or automatic retry.',provider_status=response.status_code)
    try:
        body = response.json()
        if len(response.content) > 2_000_000:
            raise ValueError('Oversized search response.')
        candidate = body['candidates'][0]
        candidate['content']['parts'] = [p if not p.get('thought') else {} for p in candidate['content']['parts']]
        metadata = candidate.get('groundingMetadata', {})
        if not metadata.get('groundingChunks') or not metadata.get('groundingSupports'):
            raise ValueError('No search citations.')
        storage.event(run_id, 'online_search', {'status': 'search response received',
                      'queries': metadata.get('webSearchQueries', [])[:12],
                      'usage': {k:v for k,v in body.get('usageMetadata', {}).items() if isinstance(v,int)}})
        return candidate
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        raise ModelUnavailable('Online search returned no usable source grounding. Model memory is not accepted as current news.') from None


async def generate(run_id, role, context, schema):
    try:
        key, model = model_settings()
    except RuntimeError as exc:
        raise ModelUnavailable(str(exc)) from None
    text = json.dumps(context, ensure_ascii=False)
    if len(text) > 70_000:
        raise ModelUnavailable('Model input budget exceeded.')
    prompt = (ROOT / 'prompts' / (role + '-v1.txt')).read_text(encoding='utf-8')
    for attempt in range(2):
        reserve_call(run_id)
        grammar=provider_schema(schema)
        if role=='updates':
            ids=[b['block_id'] for b in context.get('grounded_blocks',[]) if isinstance(b.get('block_id'),int) and b['block_id']>0]
            if ids:
                grammar['properties']['events']['items']['properties']['evidence']['items']['properties']['block_id']['enum']=ids
        payload = {'systemInstruction': {'parts': [{'text': prompt}]},
                   'contents': [{'role': 'user', 'parts': [{'text': text}]}],
                    'generationConfig': {'temperature': 0, 'maxOutputTokens': 8000 if role in ('updates','analyst') else 6000,
                                        'responseMimeType': 'application/json',
                                        'responseJsonSchema': grammar}}
        storage.event(run_id, role, {'status': 'request started', 'attempt': attempt + 1})
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(100,connect=10), trust_env=False) as client:
                response = await client.post(f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent',
                                             headers={'x-goog-api-key': key}, json=payload)
        except httpx.RequestError as exc:
            storage.event(run_id,'model_connection_failed',{'role':role,'error_type':type(exc).__name__})
            raise ModelUnavailable('Gemini connection failed. Run stopped without fallback.') from None
        if response.status_code in (500, 502, 503, 504) and attempt == 0:
            await asyncio.sleep(2)
            continue
        if response.status_code != 200:
            raise ModelUnavailable(f'Gemini returned HTTP {response.status_code}. No paid fallback; quota/authentication failures are not retried.',provider_status=response.status_code)
        try:
            body = response.json()
            parts = body['candidates'][0]['content']['parts']
            answer = ''.join(p.get('text', '') for p in parts if not p.get('thought', False))
            result = validated_response(role, schema, answer)
            usage = body.get('usageMetadata', {})
            if not isinstance(usage, dict):
                usage = {}
            # Only numeric usage counters are persisted; upstream text is untrusted.
            usage = {k: v for k, v in usage.items() if isinstance(v, int) and not isinstance(v, bool)}
        except (ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
            # Preserve bounded diagnostics only, never model reasoning, response
            # bodies or credentials. Useful to distinguish truncation/schema gaps.
            detail={'role':role,'error_type':type(exc).__name__}
            if hasattr(exc,'errors'):
                detail['fields']=[{'type':e['type'],'location':list(e['loc'])} for e in exc.errors()[:12]]
            if isinstance(locals().get('body'),dict):
                candidates = body.get('candidates')
                candidate = candidates[0] if isinstance(candidates,list) and candidates else None
                if isinstance(candidate,dict) and isinstance(candidate.get('finishReason'),str):
                    detail['finish_reason']=candidate['finishReason'][:80]
            storage.event(run_id,'model_validation_failed',detail)
            raise ModelUnavailable('Gemini returned invalid structured output. No facts or claims accepted.') from None
        storage.event(run_id, role, {'model': model, 'prompt_version': role + '-v1', 'usage': usage,
                                    'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
                                    'remaining_provider_quota': 'not exposed by generateContent'})
        return result
    raise ModelUnavailable('Transient provider failure.')
