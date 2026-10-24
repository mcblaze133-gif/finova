import tempfile
import unittest
from pathlib import Path
from backend import market_data as m


class MarketIntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
    def file(self,text,name='equity.csv'):
        p=self.root/name;p.write_text(text,encoding='utf-8');return p
    def test_slb_filename_and_settlement_headers_rejected(self):
        text='Symbol,Date,Series,Close Price\nITC,23-Oct-2026,EQ,300\n'
        with self.assertRaisesRegex(ValueError,'SLB'):m.read_prices(self.file(text,'Quote-SLB-ITC.csv'))
        with self.assertRaisesRegex(ValueError,'settlement'):m.read_prices(self.file('Symbol,Date,Series,Close Price,Settlement Date\nITC,23-Oct-2026,X1,0.2,01-Nov-2026\n'))
    def test_non_equity_series_never_becomes_a_share_price(self):
        with self.assertRaisesRegex(ValueError,'No cash-equity'):m.read_prices(self.file('Symbol,Date,Series,Close Price\nITC,23-Oct-2026,X1,0.2\n'))
    def test_nse_trimmed_headers_dates_and_number_types(self):
        p=self.file('"Symbol ","Date ","Series ","Close Price "\n"ITC","23-OCT-2026","EQ","1,234.50"\n')
        row=m.read_prices(p)[0]
        self.assertEqual(row['close'],'1234.50');self.assertEqual(row['date'],'2026-10-23');self.assertEqual(len(row['source_sha256']),64)
    def test_unified_bhavcopy_headers_supported(self):
        row=m.read_prices(self.file('TckrSymb,TradDt,SctySrs,ClsPric\nITC,2026-10-23,EQ,300\n'))[0]
        self.assertEqual(row['symbol'],'ITC')
    def test_missing_date_not_replaced_with_last_available_quote(self):
        self.file('Symbol,Date,Series,Close Price\nITC,22-Oct-2026,EQ,300\n')
        result=m.inspect_folder(self.root,['ITC'],'2026-10-23')
        self.assertFalse(result['common_date_complete']);self.assertFalse(result['candidates'])
    def test_conflicts_are_not_averaged_or_selected(self):
        self.file('Symbol,Date,Series,Close Price\nITC,23-Oct-2026,EQ,300\nITC,23-Oct-2026,EQ,310\n')
        result=m.inspect_folder(self.root,['ITC'],'2026-10-23')
        self.assertFalse(result['candidates']);self.assertIn('conflicting',result['gaps'][0])
    def test_valid_csv_is_candidate_not_authenticity_attestation(self):
        self.file('Symbol,Date,Series,Close Price\nITC,23-Oct-2026,EQ,300\n')
        result=m.inspect_folder(self.root,['ITC'],'2026-10-23')
        self.assertTrue(result['common_date_complete']);self.assertFalse(result['approved_for_valuation'])
    def test_nonfinite_zero_and_negative_prices_rejected(self):
        for value in ('NaN','Infinity','0','-5'):
            with self.assertRaises(ValueError):m.read_prices(self.file('Symbol,Date,Series,Close Price\nITC,23-Oct-2026,EQ,'+value+'\n'))

    def test_official_quote_export_filename_identifies_symbol_without_inventing_one(self):
        text='DATE,SERIES,CLOSE\n23-Oct-2026,EQ,257.90\n'
        row=m.read_prices(self.file(text,'Quote-Equity-ITC-EQ-24-09-2026-24-10-2026.csv'))[0]
        self.assertEqual(row['symbol'],'ITC')
        self.assertIn('filename',row['symbol_identification'])
        with self.assertRaisesRegex(ValueError,'symbol'):m.read_prices(self.file(text))

    def test_quote_filename_cannot_override_conflicting_row_symbol(self):
        with self.assertRaisesRegex(ValueError,'conflict'):
            m.read_prices(self.file('Symbol,DATE,SERIES,CLOSE\nHINDUNILVR,23-Oct-2026,EQ,1814.70\n','Quote-Equity-ITC-EQ-24-09-2026-24-10-2026.csv'))
