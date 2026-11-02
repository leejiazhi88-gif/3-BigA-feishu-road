"""Publish forecast changes and provenance without private worksheet notes."""
from collections import Counter
from copy import deepcopy
import csv,json,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/refresh-all-20261102'
EXPORT=ROOT/'exports/refresh_20261102'
EXPORT.mkdir(parents=True,exist_ok=True)

def save(name,value):
    (EXPORT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n')

for name in ('summary.json','additions.json','forecast_changes.json','fundamental_fetch.json','clone_verification.json','verification.json','new_company_dividend_audit.json'):
    save(name,json.loads((WORK/name).read_text()))
changes=json.loads((WORK/'forecast_changes.json').read_text())
annual=[x for x in changes if '净利润(预测,亿元)' in x['field']]
with (EXPORT/'annual_changes.csv').open('w',encoding='utf-8-sig',newline='') as stream:
    w=csv.writer(stream,lineterminator='\n');w.writerow(['代码','名称','年度','旧值（亿元）','新值（亿元）','变化比例'])
    for x in annual:w.writerow([x['code'],x['name'],x['field'][:4],x['old'],x['new'],f"{x['change_ratio']:.4%}" if x['change_ratio'] is not None else '无可比基期'])
audit=json.loads((WORK/'forecast_quality_audit.json').read_text())
for a in audit:
    for x in a['years'].values():
        exclusions=x['selection'].pop('excluded');x['selection']['excluded_counts']=dict(Counter(r['reason'] for r in exclusions));latest={}
        for r in sorted(exclusions,key=lambda r:r['date'],reverse=True):
            key=(r['broker_key'],r['reason'])
            if key not in latest:latest[key]={k:r[k] for k in ('org','date','value','reason')}
        x['selection']['latest_excluded_per_broker_reason']=list(latest.values())
save('forecast_quality_audit.json',audit)
summary=json.loads((EXPORT/'summary.json').read_text())
summary.update(annual_changes=len(annual),annual_changed_companies=len({x['code'] for x in annual}),
               forecast_status_counts=dict(Counter(x['status'] for a in audit for x in a['years'].values())),
               missing_q3=[{'name':a['name'],'code':a['code']} for a in audit if 3 not in a['years']['2026']['actual_quarters']],
               flagged_companies=sum(any(x['warnings'] for x in a['years'].values()) for a in audit),
               external_checks=sum(a['external_check'] is not None for a in audit),
               external_failures=sum(a['external_check'] is not None and a['external_check']['status']!='ok' for a in audit))
save('summary.json',summary)
save('new_business_composition.json',json.loads((ROOT/'work/composition-additions-20261102/prepared.json').read_text()))
print(json.dumps({k:v for k,v in summary.items() if k not in ('additions',)},ensure_ascii=False,indent=2))
