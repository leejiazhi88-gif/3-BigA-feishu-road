"""As-of broker consensus and explicitly labelled, reconciled quarter models.

Money is CNY 100 million. Broker report_rc.np is CNY 10 thousand.
No network or sheet mutations occur in this module.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
import math
import re
import statistics

import pandas as pd

YEARS = (2026, 2027, 2028)


def rounded(x):
    return float(Decimal(str(x)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def number(x):
    try:
        n = float(x)
        return n if math.isfinite(n) else None
    except (TypeError, ValueError):
        return None


def broker_key(name):
    return str(name).strip().replace('股份有限公司', '').replace('有限责任公司', '').replace('中银国际', '中银').replace('证券', '')


def actuals(income, asof):
    """Select latest disclosed consolidated cumulative, then difference adjacent periods."""
    f = income.copy()
    if f.empty:
        return {}, {}
    for col in ('end_date', 'ann_date', 'f_ann_date', 'report_type'):
        f[col] = f[col].fillna('').astype(str).str.replace(r'\.0$', '', regex=True)
    f['disclosed'] = f[['ann_date', 'f_ann_date']].max(axis=1)
    f = f[(f.disclosed <= asof) & (f.end_date <= asof) & f.report_type.isin(['1', '4', '5'])]
    f = f[f.n_income_attr_p.notna()].copy()
    f['rank'] = f.report_type.map({'1': 0, '4': 1, '5': 2})
    f = f.sort_values(['end_date', 'disclosed', 'rank'], ascending=[True, False, True]).drop_duplicates('end_date')
    cumulative = {r.end_date: float(r.n_income_attr_p) / 1e8 for r in f.itertuples()}
    q = {}
    for y in range(2023, 2029):
        prev = 0.0
        for n, suffix in enumerate(('0331', '0630', '0930', '1231'), 1):
            current = cumulative.get(str(y) + suffix)
            if current is not None and prev is not None:
                q[(y, n)] = current - prev
            prev = current
    return q, cumulative


def records(report, asof):
    out = []
    for r in report.to_dict('records'):
        date = str(r.get('report_date', '')).replace('-', '')[:8]
        np = number(r.get('np'))
        org = str(r.get('org_name') or '').strip()
        if not re.fullmatch(r'\d{8}', date) or date > asof or np is None or org in ('', 'nan'):
            continue
        key = str(r.get('quarter', ''))
        if not re.fullmatch(r'202[5-8]Q4', key):
            continue
        out.append({'year': int(key[:4]), 'date': date, 'org': org, 'broker_key': broker_key(org),
                    'value': np / 10000, 'title': str(r.get('report_title', '')),
                    'source': str(r['source']) if pd.notna(r.get('source')) else 'Tushare',
                    'url': str(r['url']) if pd.notna(r.get('url')) else ''})
    return out


def select(records_, year, asof, financial_date):
    groups = {}
    for r in records_:
        if r['year'] == year:
            groups.setdefault(r['broker_key'], []).append(r)
    latest, excluded = [], []
    for group in groups.values():
        newest = max(r['date'] for r in group)
        candidates = [r for r in group if r['date'] == newest]
        # Conflicting same-day records cannot be silently resolved by input order.
        if max(r['value'] for r in candidates) - min(r['value'] for r in candidates) > .05:
            excluded.extend(dict(r, reason='同机构同日预测冲突') for r in group)
            continue
        candidates.sort(key=lambda r: (r['source'] != 'Tushare', r['title']))
        latest.append(candidates[0])
        excluded.extend(dict(r, reason='旧版本或重复') for r in group if r is not candidates[0])
    now = datetime.strptime(asof, '%Y%m%d')
    valid = []
    for r in latest:
        r = dict(r, age_days=(now-datetime.strptime(r['date'], '%Y%m%d')).days)
        if r['age_days'] <= 90:
            valid.append(r)
        else:
            excluded.append(dict(r, reason='超过90天'))
    after = [r for r in valid if not financial_date or r['date'] >= financial_date]
    used = after or valid
    excluded.extend(dict(r, reason='优先采用财报后预测') for r in valid if r not in used)
    return {'used': used, 'excluded': excluded,
            'value': statistics.median(r['value'] for r in used) if used else None,
            'status': ('机构预测' if after else '财报后未更新') if used else '机构预测待更新'}


def seasonality(q):
    patterns = []
    for y in (2024, 2025):
        values = [q.get((y, i)) for i in range(1, 5)]
        if all(v is not None and v > 0 for v in values):
            weights = [v / sum(values) for v in values]
            if min(weights) >= .05 and max(weights) <= .60:
                patterns.append(weights)
    if len(patterns) == 2 and max(abs(a-b) for a,b in zip(*patterns)) <= .15:
        return [statistics.mean(x) for x in zip(*patterns)], True
    return [.25] * 4, False


def model_current(q, cumulative, industry, fallback):
    weights, stable = seasonality(q)
    available = {i: q[(2026,i)] for i in range(1,5) if (2026,i) in q}
    cyclical = any(x in industry for x in ('半导体', '元件', '消费电子', '能源金属', '工业金属', '煤炭', '钢铁', '石油'))
    if available:
        if stable and not cyclical:
            annual = sum(available.values()) / sum(weights[i-1] for i in available)
            return annual, weights, '模型估算：已披露利润按2024/25稳定季节性推算'
        latest = available[max(available)]
        forecast = sum(available.values()) + latest * (4-len(available))
        return forecast, [.25]*4, f'模型估算：未披露季度按最近Q{max(available)}实际持平'
    for year in (2025,2024,2023):
        if str(year)+'1231' in cumulative:
            return cumulative[str(year)+'1231'], weights, f'模型估算：缺当年季报，按{year}实际持平'
    if fallback is not None:
        return fallback, weights, '模型估算：缺财报，沿用表内2025基准并持平；待复核'
    raise ValueError('No financial baseline; cannot manufacture a profit')


def growth_path(records_, year, asof):
    """Use same-report adjacent annual ratios only, at most 365 days old."""
    now = datetime.strptime(asof, '%Y%m%d')
    paired = {}
    for r in records_:
        if (now-datetime.strptime(r['date'], '%Y%m%d')).days <= 365:
            paired.setdefault((r['broker_key'],r['date'],r['title']), {})[r['year']] = r
    by_org = {}
    for (org,date,title), pair in paired.items():
        a,b = pair.get(year-1),pair.get(year)
        if a and b and a['value']>0 and b['value']>0:
            ratio=b['value']/a['value']
            if .5<=ratio<=2 and (org not in by_org or date>by_org[org]['date']):
                by_org[org]={'org':a['org'],'date':date,'ratio':ratio,'base':a,'next':b}
    used=list(by_org.values())
    if used:
        latest=datetime.strptime(max(r['date'] for r in used),'%Y%m%d')
        used=[r for r in used if (latest-datetime.strptime(r['date'],'%Y%m%d')).days<=90]
    return (statistics.median(r['ratio'] for r in used),used) if used else (1.0,[])


def reconcile(annual, actual, weights):
    """Round once; allocate residual tenths only to an unreported quarter."""
    units = {q: int(Decimal(str(v)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)*10) for q,v in actual.items()}
    unknown=[q for q in range(1,5) if q not in units]
    if not unknown:
        return sum(units.values())/10, [units[i]/10 for i in range(1,5)]
    total=int(Decimal(str(annual)).quantize(Decimal('.1'),rounding=ROUND_HALF_UP)*10)
    rest=total-sum(units.values()); denom=sum(weights[q-1] for q in unknown)
    for q in unknown[:-1]:
        units[q]=int(Decimal(str(rest*weights[q-1]/denom)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
    units[unknown[-1]]=total-sum(units.values())
    return total/10,[units[i]/10 for i in range(1,5)]


def build(report,income,asof,industry='',fallback_2025=None):
    q,cum=actuals(income,asof)
    original_actual_keys=set(q)
    # If only a half-year cumulative exists (e.g. a newly listed company), do
    # not call it Q2. Split the unavailable component and label it estimated.
    imputed=[]
    for last,suffix in reversed(list(enumerate(('0331','0630','0930','1231'),1))):
        total=cum.get('2026'+suffix)
        if total is None:continue
        missing=[i for i in range(1,last+1) if (2026,i) not in q]
        if missing:
            remainder=total-sum(q.get((2026,i),0) for i in range(1,last+1))
            for i in missing:q[(2026,i)]=remainder/len(missing)
            imputed=missing
        break
    data=records(report,asof)
    dates=[]
    for r in income.to_dict('records'):
        if str(r.get('end_date','')) <= asof:
            d=max(str(r.get('ann_date','')),str(r.get('f_ann_date','')))
            if re.fullmatch(r'\d{8}',d) and d<=asof:dates.append(d)
    financial_date=max(dates) if dates else None
    baseline,weights,method=model_current(q,cum,industry,fallback_2025)
    out={}; external_needed=False
    for year in YEARS:
        s=select(data,year,asof,financial_date)
        actual={i:q[(year,i)] for i in range(1,5) if (year,i) in q}
        warnings=(['累计财报完整但单季拆分缺失，缺失季度按累计余额均分估算'] if year==2026 and imputed else [])
        model=False; path=[]
        if s['value'] is None:
            external_needed=True; model=True
        if year==2026 and s['value'] is not None and actual:
            remainder=s['value']-sum(actual.values())
            hist_negative=any(q.get((y,i),0)<0 for y in (2024,2025) for i in range(1,5) if i not in actual)
            if remainder<0 and sum(actual.values())>0:
                warnings.append('全年机构预测低于已披露累计利润')
                external_needed=True
                if s['status']=='财报后未更新' and not hist_negative:
                    model=True
            if abs(s['value']-baseline)>max(abs(baseline)*.5,1):
                warnings.append('机构预测偏离实际运行基准超过50%，需复核')
                external_needed=True
        if s['used']:
            low=min(r['value'] for r in s['used']);high=max(r['value'] for r in s['used'])
            if high-low>max(abs(s['value']),1):warnings.append('机构预测分歧较大')
        if model:
            if year==2026:
                value=baseline;label=method
            else:
                ratio,path=growth_path(data,year,asof)
                previous=out[year-1]['annual']
                value=previous*ratio if previous>0 else previous
                if previous<=0:path=[]
                label=(f'模型估算：以{year-1}年为基数，参考历史同份研报增长率{ratio-1:+.1%}'
                       if path else f'模型估算：缺可靠增长依据，按{year-1}年持平')
            status='模型估算（机构预测待更新）' if not s['used'] else '模型估算（旧预测与实际冲突）'
        else:
            value=s['value'];label=s['status'];status=s['status']
        annual,parts=reconcile(value,actual,weights)
        if len(actual)==4:status='实际';label='实际财报（显示数相加口径）'
        out[year]={'annual':annual,'quarters':parts,
                   'actual_quarters':[i for i in sorted(actual) if (year,i) in original_actual_keys],
                   'imputed_quarters':imputed if year==2026 else [],
                   'status':status,'method':label,'selection':s,'growth_path':path,'warnings':warnings,
                   'financial_date':financial_date,'asof':asof}
    return out,external_needed
