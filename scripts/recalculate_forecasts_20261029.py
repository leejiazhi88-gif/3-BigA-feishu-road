"""Repair only forecast-dependent cells in the existing October 29 sheet."""
from collections import Counter
import copy
import csv
import json
from pathlib import Path
import sys

import pandas as pd

import forecast_quality as quality
from forecast_quality_sheet import apply_result,validate_row,numeric
import refresh_all_20261012 as refresh
from business_composition import feishu_client as feishu

ROOT=Path(__file__).resolve().parents[1]
WORK=ROOT/'work/forecast-quality-20261030'
EXPORT=ROOT/'exports/forecast_quality_20261030'
ASOF='20261029'
TARGET='WYWO67'
refresh.TARGET=TARGET
ADDRESS=TARGET+'!A1:BK500'


def save(path,data):
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)+'\n')


def prepare():
    before=json.loads((WORK/'before.json').read_text())
    headers=before[0];idx={h:i for i,h in enumerate(headers)}
    values=copy.deepcopy(before);audits=[];changes=[];statuses=Counter();changed_cols=set()
    for rowno,row in enumerate(values[1:],2):
        if not row or not row[0]:continue
        row.extend(['']*(len(headers)-len(row)));old=copy.deepcopy(row)
        code=row[idx['代码']];filename=code.replace('.','_')+'.csv'
        report=pd.read_csv(WORK/'raw/report_rc'/filename)
        income=pd.read_csv(ROOT/'work/refresh-all-20261029/raw/income'/filename,
                           dtype={'ann_date':str,'f_ann_date':str,'end_date':str,'report_type':str})
        external_file=WORK/'external'/filename.replace('.csv','.json')
        external=json.loads(external_file.read_text()) if external_file.exists() else None
        if external and external['records']:
            report=pd.concat([report,pd.DataFrame(external['records'])],ignore_index=True)
        result,_=quality.build(report,income,ASOF,row[idx['申万二级']],numeric(row[idx['2025净利润(实际/预测,亿元)']]))
        apply_result(row,idx,result)
        if external and external['status']!='ok':row[idx['数据状态']]+='；外部补查失败，未视为无更新'
        row_changes=refresh.make_changes(code,row[0],old,row,idx)
        row[idx[refresh.ANNUAL_CHANGE_HEADER]]=refresh.annual_change_text(row_changes)
        for year,h in refresh.ANNUAL_CHANGE_RATE_HEADERS.items():
            a=numeric(old[idx[f'{year}净利润(预测,亿元)']]);b=result[year]['annual']
            row[idx[h]]=(b-a)/abs(a) if a not in (None,0) else ''
        changes.extend(row_changes)
        changed_cols.update(i for i,(a,b) in enumerate(zip(old,row)) if not refresh.equivalent(a,b))
        statuses.update(x['status'] for x in result.values())
        audits.append({'row':rowno,'code':code,'name':row[0],'years':result})
    # This task does not modify market data, membership, notes, business mix or locks.
    allowed={idx[h] for h in headers if h and (h.startswith(('2026 PE','2027 PE','2028 PE','2026净利润','2027净利润','2028净利润','2026Q','2027Q','2028Q'))
        or h in ('未来三年增速均值','预测来源','数据状态',refresh.ANNUAL_CHANGE_HEADER,*refresh.ANNUAL_CHANGE_RATE_HEADERS.values())) and '锁定' not in h}
    assert changed_cols<=allowed,(changed_cols-allowed)
    payloads=[]
    last=max(i for i,r in enumerate(values,1) if r and r[0])
    for i in sorted(changed_cols):
        col=refresh.column_name(i+1)
        payloads.append({'range':f'{TARGET}!{col}2:{col}{last}',
                         'values':[[r[i] if len(r)>i else ''] for r in values[1:last]]})
    save(WORK/'after.json',values);save(WORK/'write_ranges.json',payloads)
    save(WORK/'full_audit.json',audits)
    export_audits=copy.deepcopy(audits)
    for a in export_audits:
        for x in a['years'].values():
            excluded=x['selection'].pop('excluded')
            x['selection']['excluded_counts']=dict(Counter(r['reason'] for r in excluded))
            latest={}
            for r in sorted(excluded,key=lambda r:r['date'],reverse=True):
                key=(r['broker_key'],r['reason'])
                if key not in latest:latest[key]={k:r[k] for k in ('org','date','value','reason')}
            x['selection']['excluded_latest_per_broker_reason']=list(latest.values())
    save(EXPORT/'audit.json',export_audits);save(EXPORT/'changes.json',changes)
    with (EXPORT/'annual_changes.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream,lineterminator='\n');writer.writerow(['代码','名称','年度','旧值（亿元）','新值（亿元）','变化率'])
        for x in changes:
            if '净利润(预测' in x['field']:
                writer.writerow([x['code'],x['name'],x['field'][:4],x['old'],x['new'],
                                 f"{x['change_ratio']:.2%}" if x['change_ratio'] is not None else '基期为0或缺失'])
    save(EXPORT/'external_checks.json',json.loads((WORK/'external_checks.json').read_text()))
    save(EXPORT/'fetch_log.json',json.loads((WORK/'fetch_log.json').read_text()))
    summary={'sheet':TARGET,'asof':ASOF,'companies':len(audits),'annual_checks':len(audits)*3,
             'status_counts':dict(statuses),'changed_companies':len({x['code'] for x in changes}),
             'annual_changes':sum('净利润(预测' in x['field'] for x in changes),
             'annual_changed_companies':len({x['code'] for x in changes if '净利润(预测' in x['field']}),
             'flagged_companies':sum(any(x['warnings'] for x in a['years'].values()) for a in audits),
             'columns_written':[headers[i] for i in sorted(changed_cols)],
             'source_company_count':sum(any(r['source']!='Tushare' for x in a['years'].values()
                 for r in x['selection']['used']) for a in audits)}
    save(EXPORT/'summary.json',summary);print(json.dumps(summary,ensure_ascii=False,indent=2))


def comparable(v,width):return [(r+['']*width)[:width] for r in v]


def display_value(value):
    # Feishu automatically converts URL-containing strings to rich-text runs.
    if isinstance(value,list) and all(isinstance(x,dict) and 'text' in x for x in value):
        return ''.join(x['text'] for x in value)
    return value


def apply():
    before=json.loads((WORK/'before.json').read_text());after=json.loads((WORK/'after.json').read_text())
    t=feishu.get_token();current=feishu.read_range(t,ADDRESS)
    assert current==before,'Online sheet changed after snapshot; stop before writes'
    ranges=json.loads((WORK/'write_ranges.json').read_text())
    for i in range(0,len(ranges),5):
        feishu.api(feishu.BASE+'/values_batch_update',t,'POST',{'valueRanges':ranges[i:i+5]})
    visible=[after[0]]+[r for r in after[1:] if r and r[0]]
    idx={h:i for i,h in enumerate(after[0])}
    changed_cols={r['range'].split('!')[1].split('2:')[0] for r in ranges}
    styles=refresh.font_style_payload(visible)+refresh.annual_change_style_payload(visible)+refresh.annual_change_rate_style_payload(visible)
    for item in styles:
        item['ranges']=[r for r in item['ranges'] if ''.join(c for c in r.split('!')[1].split(':')[0] if c.isalpha()) in changed_cols]
    styles=[s for s in styles if s['ranges']]
    for i in range(0,len(styles),30):feishu.api(feishu.BASE+'/styles_batch_update',t,'PUT',{'data':styles[i:i+30]})
    verify(t)


def verify(t=None):
    t=t or feishu.get_token()
    before=json.loads((WORK/'before.json').read_text());after=json.loads((WORK/'after.json').read_text())
    current=feishu.read_range(t,ADDRESS);width=len(after[0]);idx={h:i for i,h in enumerate(after[0])}
    errors=[]
    for n,(expected,actual) in enumerate(zip(comparable(after,width),comparable(current,width)),1):
        for c,(a,b) in enumerate(zip(expected,actual)):
            if not refresh.equivalent(display_value(a),display_value(b)):errors.append((n,c+1,a,b))
    assert len(current)==len(after) and not errors,errors[:10]
    checks=0
    for row in current[1:]:
        if row and row[0]:validate_row(row,idx);checks+=3
    cf=feishu.condition_formats(t,TARGET);filter_=feishu.sheet_filter(t,TARGET)
    assert cf['data']==json.loads((WORK/'cf_before.json').read_text())['data'],'Conditional formatting changed'
    assert filter_['data']==json.loads((WORK/'filter_before.json').read_text())['data'],'Filter changed'
    save(WORK/'verified.json',current)
    summary={'rows':checks//3,'annual_reconciliations_passed':checks,'value_errors':0,
             'conditional_formats_preserved':True,'filter_preserved':True,
             'all_unedited_cells_preserved':True,'notes_and_locks_preserved':True}
    save(EXPORT/'verification.json',summary);print(json.dumps(summary,ensure_ascii=False))


if __name__=='__main__':
    {'prepare':prepare,'apply':apply,'verify':verify}[sys.argv[1]]()
