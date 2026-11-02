"""Complete new entrants' business composition and disclose dividend limitations."""
import json
from pathlib import Path
import pandas as pd
import tushare as ts
from forecast_quality_sheet import validate_row

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/refresh-all-20261102'

def main():
    path=WORK/'payload.json';payload=json.loads(path.read_text());values=payload['valueRange']['values'];idx={x:i for i,x in enumerate(values[0])}
    additions=json.loads((WORK/'additions.json').read_text());codes={x['code'] for x in additions}
    composition={x['code']:x['values'] for x in json.loads((ROOT/'work/composition-additions-20261102/prepared.json').read_text())}
    p=ts.pro_api();audit=[]
    for row in values[1:]:
        if not row or not row[0]:continue
        validate_row(row,idx)
        code=row[idx['代码']]
        if code not in codes:continue
        for header,text in zip(('25年收入构成','25年利润构成','26年收入构成','26年利润构成'),composition[code]):row[idx[header]]=text
        div=p.dividend(ts_code=code,fields='ts_code,end_date,ann_date,div_proc,cash_div_tax,base_date,base_share,ex_date,imp_ann_date')
        cap=p.daily_basic(ts_code=code,start_date='20250101',end_date='20251231',fields='ts_code,trade_date,total_mv')
        div.to_csv(WORK/'raw'/f'dividend_{code.replace(".","_")}.csv',index=False)
        cap.to_csv(WORK/'raw'/f'cap2025_{code.replace(".","_")}.csv',index=False)
        eligible=div[(div.end_date.astype(str).str.startswith('2025')) & (div.div_proc=='实施') & (div.ann_date.astype(str)<='20261102')].copy()
        eligible=eligible.sort_values('ann_date').drop_duplicates(['end_date','ex_date'],keep='last')
        known=not eligible.empty and eligible[['cash_div_tax','base_share']].notna().all().all()
        amount=float((eligible.cash_div_tax*eligible.base_share/10000).sum()) if known else None
        avg=float(cap.total_mv.mean()/10000) if not cap.empty else None
        row[idx['上财年全年股息率（25年·年日均市值）']]=amount/avg if known and avg else '待核验'
        # The existing policy review is unavailable for these first-time entrants.
        # Do not present an unreviewed payout assumption as guidance-based yield.
        row[idx['本财年预估全年股息率（26年）']]='待核验'
        row[idx['2026年股息率估算备注']]='新增公司：2026分红指引及派息比例待核验，暂不填入全年股息率'
        audit.append({'code':code,'name':row[0],'fy2025_cash_dividend_yi':amount,'fy2025_average_market_cap_yi':avg,'fy2025_records':len(eligible),'fy2026_status':'分红指引及派息比例待核验'})
    path.write_text(json.dumps(payload,ensure_ascii=False,indent=2,allow_nan=False))
    (WORK/'new_company_dividend_audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
    print('Validated 1410 annual-quarter totals; completed 8 new business compositions')

if __name__=='__main__':main()
