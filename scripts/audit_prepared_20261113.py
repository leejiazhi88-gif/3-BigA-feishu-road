"""Validate and publish November 13 preparation without claiming online completion."""
import csv,json,re,sys
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from forecast_quality_sheet import validate_row
W=ROOT/'work/refresh-all-20261113';E=ROOT/'exports/refresh_20261113';E.mkdir(exist_ok=True,parents=True)
def save(name,v):(E/name).write_text(json.dumps(v,ensure_ascii=False,indent=2,allow_nan=False)+'\n')
def main():
    p=json.loads((W/'payload_dividends.json').read_text());v=p['valueRange']['values'];h=v[0];idx={s:i for i,s in enumerate(h)}
    source=json.loads((W/'source_values.json').read_text());si={s:i for i,s in enumerate(source[0])}
    old={r[si['代码']]:r for r in source[1:] if r and r[0]}
    rows=[r for r in v[1:] if r and r[0]];assert len(rows)==478
    codes={r[idx['代码']] for r in rows};assert len(codes)==len(rows) and set(old)<=codes
    preserve=[s for s in source[0] if s.startswith('笔记')]+['25年收入构成','25年利润构成','26年收入构成','26年利润构成']
    for r in rows:
        validate_row(r,idx);code=r[idx['代码']]
        assert all(r[idx[k]] not in ('',None) for k in ('股息率%','上财年全年股息率（25年·年日均市值）','本财年预估全年股息率（26年）'))
        assert r[idx['2026Q4锁定预测(亿元)']]==r[idx['2026Q4净利润(亿元)']]
        for k in preserve:
            if code in old:assert r[idx[k]]==old[code][si[k]],(code,k)
        expected='2026-11-11' if code=='600185.SH' else '2026-11-13'
        assert r[idx['最新交易日']]==expected
        a=r[idx['2027净利润同比%(预测)']];b=r[idx['2028净利润同比%(预测)']]
        if isinstance(a,(float,int)) and isinstance(b,(float,int)):assert r[idx['27/28利润增速均值']]==(a+b)/2
    changes=json.loads((W/'forecast_changes.json').read_text())
    annual=[x for x in changes if re.fullmatch(r'20\d{2}净利润\(预测,亿元\)',x['field'])]
    with (E/'annual_changes.csv').open('w',encoding='utf-8-sig',newline='') as f:
        out=csv.writer(f,lineterminator='\n');out.writerow(['代码','名称','年度','旧值（亿元）','新值（亿元）','变化比例'])
        for x in annual:out.writerow([x['code'],x['name'],x['field'][:4],x['old'],x['new'],f"{x['change_ratio']:.4%}" if x['change_ratio'] is not None else '无可比基期'])
    summary=json.loads((W/'summary.json').read_text())
    summary.update(status='prepared_pending_ui_copy',online_written=False,source_sheet='lxu8og',source_rule_count=17,
        annual_changes=len(annual),annual_changed_companies=len({x['code'] for x in annual}),
        annual_quarter_reconciliations=len(rows)*3,personal_notes_preserved=3,
        q4_lock_prepared=True,q4_lock_written=False,
        blocker='需要在飞书界面复制2026-11-06（新）为2026-11-13，当前会话无浏览器工具。')
    save('summary.json',summary)
    for name in ['additions.json','forecast_changes.json','fundamental_fetch.json','suspended.json']:
        save(name,json.loads((W/name).read_text()))
    save('dividend_backfill_audit.json',json.loads((W/'payload_dividends.audit.json').read_text()))
    audits=json.loads((W/'forecast_quality_audit.json').read_text())
    compact=[]
    for a in audits:
        for y in a['years'].values():
            excluded=y['selection'].pop('excluded');y['selection']['excluded_counts']=dict(Counter(x['reason'] for x in excluded))
        compact.append(a)
    save('forecast_quality_audit.json',compact)
    save('prepared_validation.json',{'rows':len(rows),'annual_quarter_reconciliations':len(rows)*3,'notes_columns_preserved':3,'business_composition_preserved':True,'q4_locks_match_current_forecasts':True,'online_written':False})
    print(json.dumps(summary,ensure_ascii=False))
if __name__=='__main__':main()
