"""Complete new entrants and dividend blanks without modifying a live sheet."""
import json,os,runpy,sys
from pathlib import Path
import tushare as ts
ROOT=Path(__file__).resolve().parents[1];W=ROOT/'work/refresh-all-20261120'
def main():
 p=json.loads((W/'payload.json').read_text());v=p['valueRange']['values'];idx={x:i for i,x in enumerate(v[0])}
 composition={x['code']:x['values'] for x in json.loads((ROOT/'work/composition-additions-20261120/prepared.json').read_text())}
 dates={}
 for row in v[1:]:
  if not row or not row[0]:continue
  code=row[idx['代码']]
  if code in composition:
   for h,text in zip(('25年收入构成','25年利润构成','26年收入构成','26年利润构成'),composition[code]):row[idx[h]]=text
  dates[code]=row[idx['最新交易日']]
  row[idx['最新交易日']]='2026-11-20'
 (W/'dividend_input.json').write_text(json.dumps(p,ensure_ascii=False,indent=2,allow_nan=False))
 if not os.environ.get('TUSHARE_TOKEN'):os.environ['TUSHARE_TOKEN']=ts.get_token()
 sys.argv=['fill_dividend_payload.py','--input',str(W/'dividend_input.json'),'--output',str(W/'payload_dividends.json'),'--asof','2026-11-20']
 runpy.run_path(str(ROOT/'scripts/fill_dividend_payload.py'),run_name='__main__')
 p=json.loads((W/'payload_dividends.json').read_text())
 for row in p['valueRange']['values'][1:]:
  if row and row[0]:row[idx['最新交易日']]=dates[row[idx['代码']]]
 (W/'payload_dividends.json').write_text(json.dumps(p,ensure_ascii=False,indent=2,allow_nan=False))
if __name__=='__main__':main()
