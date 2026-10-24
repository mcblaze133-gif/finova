"""Inspect user-supplied price CSVs without changing any company valuation."""
import argparse,json
from backend import storage,market_data


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--folder',required=True);p.add_argument('--date',required=True);args=p.parse_args()
    result=market_data.inspect_folder(args.folder,['BRITANNIA','HINDUNILVR','ITC','NESTLEIND','TATACONSUM'],args.date)
    path=storage.PROJECT_DIR/'reports/market-intake.json';path.write_text(json.dumps(result,indent=2),encoding='utf-8')
    for row in result['files']:print(row['file'],row['status'],row.get('reason',''))
    print('Common-date equity prices available:',result['common_date_complete'])
    print('Valuation prices changed: False')


if __name__=='__main__':main()
