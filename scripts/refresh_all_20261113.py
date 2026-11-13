#!/usr/bin/env python3
"""Prepare November 13 data read-only from the latest complete source sheet.

The live target must be a full UI copy; this command never writes to Feishu.
Preserves three personal-note columns and the added 2027/2028 growth column.
"""
import importlib.util
import json
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('worker_1113',ROOT/'scripts/refresh_all_20261012.py')
w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
w.TARGET='lxu8og'
w.ASOF='20261113';w.ASOF_DISPLAY='2026-11-13';w.TITLE='2026-11-13'
w.WORK=ROOT/'work/refresh-all-20261113';w.RAW=w.WORK/'raw'
w.WORK.mkdir(exist_ok=True,parents=True);w.RAW.mkdir(exist_ok=True)
w.INDUSTRY_COLOR_MAP=ROOT/'config/industry_color_map_20261106.json'
w.PERSONAL_NOTE_STYLE_MAP=ROOT/'config/personal_note_colors_20261106.json'
RENAMES={'笔记1 细分归类（AI别刷新这块）':'笔记（AI别刷新这部分，我自己记录）',
         '笔记2 26Q3财报季（AI也别刷新）':'笔记2 决策（AI也别刷新）'}
EXTRAS=('笔记3 动作','27/28利润增速均值')

def main():
    original_read=w.feishu.read_range
    captured={}
    def normalized_read(token,address):
        values=original_read(token,address)
        if values and values[0][0]=='名称':
            captured['values']=values
            hs=values[0];keep=[i for i,h in enumerate(hs) if h not in EXTRAS]
            return [[RENAMES.get(hs[i],hs[i]) for i in keep]]+[
                [(r+['']*len(hs))[i] for i in keep] for r in values[1:]]
        return values
    w.feishu.read_range=normalized_read
    # Keep a suspended holding using its last verified close; never invent a
    # current-day quote. The output explicitly retains its actual quote date.
    original_market=w.fetch_market
    suspended={}
    def market(pro):
        daily,stocks,companies=original_market(pro)
        src=captured['values'];ci=src[0].index('代码')
        missing={r[ci] for r in src[1:] if r and r[0]}-set(daily.ts_code)
        for code in sorted(missing):
            halt=w.query(pro,'suspend_d',ts_code=code,trade_date=w.ASOF)
            assert not halt.empty and halt.suspend_type.eq('S').any(),code
            prior=w.query(pro,'daily_basic',ts_code=code,start_date='20261001',end_date=w.ASOF,
                fields='ts_code,trade_date,close,pe_ttm,dv_ttm,total_mv,total_share')
            assert not prior.empty,code
            latest=prior.sort_values('trade_date').tail(1)
            suspended[code]=str(latest.iloc[0].trade_date)
            daily=w.pd.concat([daily,latest],ignore_index=True)
        return daily,stocks,companies
    w.fetch_market=market
    original_price=w.fetch_price
    def price(code,pro):
        if code not in suspended:return original_price(code,pro)
        path=w.RAW/'prices'/f'{w.code_file(code)}.csv';path.parent.mkdir(exist_ok=True)
        frame=w.query(pro,'daily',ts_code=code,start_date='20220101',end_date=w.ASOF,
                      fields='ts_code,trade_date,close,pct_chg')
        assert str(frame.trade_date.max())==suspended[code]
        frame.to_csv(path,index=False)
        return code
    w.fetch_price=price
    original_query=w.query
    def paced_query(pro,endpoint,**kw):
        for attempt in range(3):
            try:
                time.sleep(.4)
                return original_query(pro,endpoint,**kw)
            except Exception as exc:
                if '频率超限' not in str(exc) or attempt==2:raise
                time.sleep(30)
    w.query=paced_query
    w.prepare()
    source=captured['values'];(w.WORK/'source_values.json').write_text(json.dumps(source,ensure_ascii=False,indent=2))
    sh=source[0];si={h:i for i,h in enumerate(sh)}
    old={r[si['代码']]:r+['']*len(sh) for r in source[1:] if r and r[0]}
    p=json.loads((w.WORK/'payload.json').read_text());hs=p['valueRange']['values'][0]
    desired=sh.copy()
    if w.Q4_LOCK_HEADER in hs and w.Q4_LOCK_HEADER not in desired:
        desired.insert(desired.index(w.Q4_NORMAL_HEADER),w.Q4_LOCK_HEADER)
    hi={h:i for i,h in enumerate(hs)};rows=[desired]
    for r in p['valueRange']['values'][1:]:
        if not r or not r[0]:rows.append(['']*len(desired));continue
        code=r[hi['代码']];base=old.get(code)
        out=[]
        for h in desired:
            if h=='笔记3 动作':out.append(base[si[h]] if base else '')
            elif h=='27/28利润增速均值':
                a=r[hi['2027净利润同比%(预测)']];b=r[hi['2028净利润同比%(预测)']]
                out.append((a+b)/2 if isinstance(a,(int,float)) and isinstance(b,(int,float)) else '基期为0或缺失')
            else:out.append(r[hi[RENAMES.get(h,h)]])
        if code in suspended:
            date=suspended[code];shown=f'{date[:4]}-{date[4:6]}-{date[6:]}'
            out[desired.index('最新交易日')]=shown
            out[desired.index('当日涨幅%')]='停牌'
            k=desired.index('数据状态');out[k]=str(out[k])+'；11月13日停牌，行情沿用'+shown
        rows.append(out)
    p['valueRange']={'range':f'PENDING_UI_COPY!A1:{w.column_name(len(desired))}{len(rows)}','values':rows}
    (w.WORK/'payload.json').write_text(json.dumps(p,ensure_ascii=False,indent=2,allow_nan=False))
    (w.WORK/'suspended.json').write_text(json.dumps(suspended,ensure_ascii=False,indent=2))
    print('Prepared locally; UI copy is required before online write.',flush=True)

if __name__=='__main__':main()
