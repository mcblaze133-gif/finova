"""Conservative local NSE cash-equity CSV intake; candidates are not live quotes."""
import csv
import hashlib
import io
import re
from datetime import date,datetime
from decimal import Decimal,InvalidOperation
from pathlib import Path

ALIASES={'symbol':{'symbol','tckrsymb'},'series':{'series','sctysrs'},
         'date':{'date','timestamp','traddt'},'close':{'close','closeprice','clspric'}}


def key(value):return re.sub(r'[^a-z0-9]','',value.casefold())


def trade_date(value):
    for fmt in ('%Y-%m-%d','%d-%b-%Y','%d-%B-%Y','%d-%m-%Y','%d/%m/%Y'):
        try:return datetime.strptime(value.strip(),fmt).date()
        except ValueError:pass
    raise ValueError('Unrecognised trading date; no ambiguous date conversion applied.')


def read_prices(path):
    path=Path(path)
    if 'slb' in path.name.casefold():raise ValueError('SLB lending-fee export is not a cash-equity share-price source.')
    if path.stat().st_size>5_000_000:raise ValueError('Price CSV exceeds the five-megabyte intake limit.')
    raw=path.read_bytes()
    reader=csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
    headers=reader.fieldnames or []
    if len({key(h) for h in headers})!=len(headers):raise ValueError('Ambiguous duplicate CSV headers.')
    if any(key(h) in ('settlementdate','reverselegsettlementdate','lendingfee') for h in headers):
        raise ValueError('SLB/settlement-contract fields cannot establish a cash-equity closing price.')
    columns={}
    quote_file=re.fullmatch(r'Quote-Equity-([A-Z0-9&-]{1,30})-EQ-\d{2}-\d{2}-\d{4}-\d{2}-\d{2}-\d{4}\.csv',path.name)
    file_symbol=quote_file.group(1) if quote_file else None
    for field,aliases in ALIASES.items():
        found=[h for h in headers if key(h) in aliases]
        if field=='symbol' and not found and file_symbol:
            continue # NSE quote exports identify the instrument in the filename.
        if len(found)!=1:raise ValueError('One unambiguous '+field+' column is required.')
        columns[field]=found[0]
    observations=[]
    for index,row in enumerate(reader,2):
        if index>100_001:raise ValueError('Price CSV exceeds the row limit.')
        if None in row:raise ValueError('Malformed CSV row.')
        series=(row.get(columns['series']) or '').strip().upper()
        if series!='EQ':continue # never reinterpret an SLB/futures/debt series
        symbol=(row.get(columns['symbol']) or '').strip().upper() if 'symbol' in columns else file_symbol
        if file_symbol and symbol!=file_symbol:raise ValueError('Filename and row symbol conflict.')
        if not re.fullmatch(r'[A-Z0-9&-]{1,30}',symbol):raise ValueError('Invalid equity symbol.')
        try:price=Decimal((row.get(columns['close']) or '').replace(',','').strip())
        except InvalidOperation:raise ValueError('Invalid closing price.') from None
        if not price.is_finite() or price<=0:raise ValueError('Closing price must be finite and positive.')
        observations.append({'symbol':symbol,'date':trade_date(row.get(columns['date']) or '').isoformat(),
                             'close':str(price),'series':'EQ','currency':'INR','source_file':path.name,
                             'source_sha256':hashlib.sha256(raw).hexdigest(),'csv_row':index,
                             'symbol_identification':'CSV column' if 'symbol' in columns else 'NSE quote-export filename; requires source-origin review',
                             'verification':'CSV format and series checked; local copy origin, corporate actions and official authenticity require review.'})
    if not observations:raise ValueError('No cash-equity EQ observations found. No price imported.')
    return observations


def inspect_folder(folder,symbols,on_date):
    from backend import storage
    if not isinstance(on_date,date):on_date=date.fromisoformat(on_date)
    if on_date>storage.today_ist():raise ValueError('Requested trading date cannot be in the future.')
    root=Path(folder)
    if not root.is_dir():raise ValueError('Price-data folder not found.')
    observations=[];files=[]
    for path in sorted(root.glob('*.csv')):
        try:
            records=read_prices(path);observations.extend(records)
            files.append({'file':path.name,'status':'format_checked','equity_rows':len(records)})
        except (ValueError,OSError,UnicodeError,csv.Error) as exc:
            files.append({'file':path.name,'status':'rejected','reason':str(exc)})
    selected=[];gaps=[]
    for symbol in sorted(set(symbols)):
        found=[r for r in observations if r['symbol']==symbol and r['date']==on_date.isoformat()]
        if not found:gaps.append(symbol+': no EQ closing price on the requested common date')
        elif len({Decimal(r['close']) for r in found})!=1:gaps.append(symbol+': conflicting closes; no price selected')
        else:selected.append({'symbol':symbol,'date':on_date.isoformat(),'close':found[0]['close'],'evidence':found})
    return {'checked_at':storage.now(),'requested_date':on_date.isoformat(),'files':files,'candidates':selected,
            'gaps':gaps,'common_date_complete':not gaps,'approved_for_valuation':False,
            'policy':'Intake does not overwrite model prices. Source authenticity, price-date share count, corporate actions and peer/earnings normalisation must be reviewed before valuation use.'}
