"""Apply the quality-controlled forecast to existing header-mapped row values."""
import math
import re
from decimal import Decimal
from forecast_quality import YEARS


def numeric(value):
    match=re.match(r'[-+]?\d+(?:\.\d+)?',str(value or ''))
    return float(match[0]) if match else (0.0 if value==0 else None)


def apply_result(row,idx,result):
    def put(h,v):row[idx[h]]=v
    cap=numeric(row[idx['市值(亿元)']]);previous=numeric(row[idx['2025净利润(实际/预测,亿元)']])
    growth=[];sources=[];states=[]
    for year in YEARS:
        x=result[year];annual=x['annual']
        put(f'{year}净利润(预测,亿元)',annual)
        put(f'{year} PE(预测)',round(cap/annual,1) if cap and annual>0 else '亏损' if annual<0 else '不适用')
        yoy=(annual-previous)/abs(previous) if previous is not None and previous!=0 else None
        put(f'{year}净利润同比%(预测)',round(yoy,6) if yoy is not None else '基期为0或缺失')
        if yoy is not None:growth.append(yoy)
        previous=annual
        for q,value in enumerate(x['quarters'],1):
            h=f'{year}Q{q}净利润(亿元)';old=str(row[idx[h]] or '')
            if q in x['actual_quarters'] and '（' in old:
                value=f'{value:.1f}'+old[old.index('（'):]
            elif q in x.get('imputed_quarters',[]):
                value=f'{value:.1f}（累计拆分估算）'
            put(h,value)
        used=x['selection']['used']
        if x['status'].startswith('模型'):
            desc=x['method']
            if x['growth_path']:
                dates=sorted({r['date'] for r in x['growth_path']})
                desc+=f"（{len(x['growth_path'])}家，研报{dates[0]}至{dates[-1]}；历史路径仅参考）"
            stale_dates=[r['date'] for r in x['selection']['excluded'] if r['reason']=='超过90天']
            if stale_dates:desc+='；最近过期研报'+max(stale_dates)
        else:
            desc=f"机构中位数（{len(used)}家，最新{max(r['date'] for r in used)}，{x['status']}）" if used else x['method']
        # The user's default source is Tushare; label only external contributions.
        external=[r for r in used if r['source']!='Tushare'] if not x['status'].startswith('模型') else []
        external += [p['next'] for p in x['growth_path'] if p['next']['source']!='Tushare']
        if external:
            desc+='；非Tushare：'+'、'.join(sorted({r['org']+' '+r['date']+' '+r['url'] for r in external}))
        sources.append(f'{year}：{desc}')
        if x['status']!='机构预测':states.append(f"{year}：{x['status']}")
        if len(used)==1 and not x['status'].startswith('模型'):states.append(f'{year}：仅1家机构')
        states.extend(f'{year}：'+s for s in x['warnings'])
    put('未来三年增速均值',sum(growth)/3 if len(growth)==3 else '基期为0或缺失')
    put('预测来源','；\n'.join(sources))
    put('数据状态','；'.join(states) if states else 'OK（逐机构最新预测，90天内）')
    validate_row(row,idx)


def validate_row(row,idx):
    for year in YEARS:
        total=numeric(row[idx[f'{year}净利润(预测,亿元)']])
        quarters=[numeric(row[idx[f'{year}Q{q}净利润(亿元)']]) for q in range(1,5)]
        assert total is not None and all(x is not None and math.isfinite(x) for x in quarters)
        assert sum(Decimal(str(v)) for v in quarters)==Decimal(str(total)),(year,total,quarters)
