#!/usr/bin/env python3
"""Refresh the intraday A-share sheet through column Q."""
from __future__ import annotations

import concurrent.futures
import json
import math
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests
import tushare as ts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work' / 'refresh-realtime-20261013'
RAW = WORK / 'raw'
WORK.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))

from business_composition import feishu_client as feishu
from industry_colors import style_payload as industry_style_payload

TARGET = 'Wc32bt'
PRIOR_CLOSE_DATE = '20261012'
PERIODS = (10, 30, 60, 90, 250, 360, 720, 1080)
HEADERS = [
    '名称', '笔记（AI别刷新这部分，我自己记录）', '申万一级', '申万二级', '代码',
    '公司产品简介', '市值(亿元)', 'PE(TTM)', '当日盘中实时涨幅%', '10日涨幅%',
    '30日涨幅%', '60日涨幅%', '90日涨幅%', '250日涨幅%', '360日涨幅%',
    '720日涨幅%', '1080日涨幅%',
]


def save(name, value):
    (WORK / name).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                        allow_nan=False))


def query(pro, endpoint, **kwargs):
    for attempt in range(4):
        try:
            time.sleep(.18)
            return getattr(pro, endpoint)(**kwargs)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def number(value):
    if value in ('', None) or isinstance(value, bool):
        return None
    match = re.match(r'[-+]?\d+(?:\.\d+)?', str(value).strip())
    if not match:
        return None
    result = float(match.group())
    return result if math.isfinite(result) else None


def column_name(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def fetch_industries(pro):
    l1 = query(pro, 'index_classify', level='L1', src='SW2021',
               fields='index_code,industry_name')
    l2 = query(pro, 'index_classify', level='L2', src='SW2021',
               fields='index_code,industry_name')
    frames = []
    for code in l1.index_code.dropna().astype(str):
        frame = query(pro, 'index_member_all', l1_code=code, is_new='Y',
                      fields='l1_code,l2_code,l2_name,ts_code,name,in_date,is_new')
        if not frame.empty:
            frames.append(frame)
    members = pd.concat(frames, ignore_index=True)
    members = members[members.is_new.astype(str).eq('Y')]
    members = members.sort_values(['ts_code', 'in_date']).drop_duplicates('ts_code', keep='last')
    members['l1_name'] = members.l1_code.map(l1.set_index('index_code').industry_name)
    members['l2_name'] = members.l2_code.map(l2.set_index('index_code').industry_name).fillna(members.l2_name)
    members.to_csv(RAW / 'industry_members.csv', index=False)
    return members


def quote_timestamp(codes):
    quotes = ts.get_realtime_quotes([code.split('.')[0] for code in codes[:3]])
    stamps = pd.to_datetime(quotes['date'].astype(str) + ' ' + quotes['time'].astype(str))
    stamp = stamps.max()
    assert stamp.strftime('%Y%m%d') == '20261013', stamp
    return stamp


def fetch_history(code, pro, prior_daily):
    old_path = ROOT / 'work/refresh-all-20261012/raw/prices' / f"{code.replace('.', '_')}.csv"
    if old_path.exists():
        history = pd.read_csv(old_path, dtype={'trade_date': str})
    else:
        history = query(pro, 'daily', ts_code=code, start_date='20220101',
                        end_date=PRIOR_CLOSE_DATE,
                        fields='ts_code,trade_date,close,pct_chg')
    supplement = prior_daily[prior_daily.ts_code.astype(str).eq(code)]
    history = pd.concat([history, supplement], ignore_index=True)
    history['trade_date'] = history.trade_date.astype(str)
    history = history.sort_values('trade_date').drop_duplicates('trade_date', keep='last')
    path = RAW / 'prices' / f"{code.replace('.', '_')}.csv"
    path.parent.mkdir(exist_ok=True)
    history.to_csv(path, index=False)
    return code, history


def style_payload(values, industry_styles, note_styles):
    idx = {header: i for i, header in enumerate(values[0])}
    styles = list(industry_styles)
    note_groups = {}
    pe_groups = {}
    for row_number, row in enumerate(values[1:], 2):
        if not row or not row[0]:
            continue
        row = list(row) + [''] * (len(HEADERS) - len(row))
        code = str(row[idx['代码']])
        note = note_styles.get(code, {'backColor': '#FFFFFF', 'foreColor': '#000000'})
        note_groups.setdefault(json.dumps(note, sort_keys=True), []).append(
            f'{TARGET}!B{row_number}:B{row_number}')
        pe = number(row[idx['PE(TTM)']])
        color = '#00B050' if pe is not None and pe < 30 else '#C00000' if pe is not None and pe > 50 else '#000000'
        pe_groups.setdefault(color, []).append(f'{TARGET}!H{row_number}:H{row_number}')
    for encoded, ranges in note_groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({'ranges': ranges[start:start + 100],
                           'style': json.loads(encoded)})
    for color, ranges in pe_groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({'ranges': ranges[start:start + 100],
                           'style': {'foreColor': color}})
    return styles


def prepare():
    token = feishu.get_token()
    before = feishu.read_range(token, f'{TARGET}!A1:Q500')
    assert before[0] == HEADERS
    rows = [list(row) + [''] * (len(HEADERS) - len(row))
            for row in before[1:] if row and row[0]]
    idx = {header: i for i, header in enumerate(HEADERS)}
    existing = {str(row[idx['代码']]): row for row in rows}
    assert len(existing) == len(rows) == 451
    save('before.json', before)
    save('conditional_formats_before.json', feishu.condition_formats(token, TARGET))
    save('filter_before.json', feishu.sheet_filter(token, TARGET))
    save('metadata_before.json', feishu.metadata(token, TARGET))

    pro = ts.pro_api()
    realtime = ts.realtime_list(src='dc')
    realtime.columns = [str(column).lower() for column in realtime.columns]
    realtime.to_csv(RAW / 'realtime_list.csv', index=False)
    assert len(realtime) > 5500 and realtime.ts_code.nunique() == len(realtime)
    stamp = quote_timestamp(list(existing))
    prior_daily = query(pro, 'daily', trade_date=PRIOR_CLOSE_DATE,
                        fields='ts_code,trade_date,close,pct_chg')
    prior_basic = query(pro, 'daily_basic', trade_date=PRIOR_CLOSE_DATE,
                        fields='ts_code,trade_date,close,pe_ttm,total_mv,total_share')
    stocks = query(pro, 'stock_basic', exchange='', list_status='L',
                   fields='ts_code,name')
    companies = pd.concat([
        query(pro, 'stock_company', exchange=exchange,
              fields='ts_code,main_business') for exchange in ('SSE', 'SZSE', 'BSE')
    ], ignore_index=True).drop_duplicates('ts_code')
    members = fetch_industries(pro)
    prior_daily.to_csv(RAW / 'daily_20261012.csv', index=False)
    prior_basic.to_csv(RAW / 'daily_basic_20261012.csv', index=False)

    market = realtime.merge(stocks, on='ts_code', how='left', suffixes=('', '_basic'))
    market = market.merge(companies, on='ts_code', how='left')
    market = market.merge(members[['ts_code', 'l1_code', 'l2_code', 'l1_name', 'l2_name']],
                          on='ts_code', how='left')
    market['cap_yi'] = pd.to_numeric(market.total_mv, errors='coerce') / 1e8
    eligible = market.dropna(subset=['l1_code', 'l2_code', 'l1_name', 'l2_name']).copy()
    threshold = eligible[eligible.cap_yi > 600]
    top2 = (eligible.sort_values(['l2_code', 'cap_yi', 'ts_code'],
                                 ascending=[True, False, True])
            .groupby('l2_code', sort=False).head(2))
    qualified = pd.concat([threshold, top2]).drop_duplicates('ts_code')
    additions = sorted(set(qualified.ts_code.astype(str)) - set(existing))
    selected = market[market.ts_code.astype(str).isin(set(existing) | set(additions))].copy()
    assert len(selected) == len(existing) + len(additions)
    l1_cap = eligible.groupby('l1_code').cap_yi.sum().to_dict()
    l2_cap = eligible.groupby('l2_code').cap_yi.sum().to_dict()
    selected['l1_cap_yi'] = selected.l1_code.map(l1_cap).fillna(-1)
    selected['l2_cap_yi'] = selected.l2_code.map(l2_cap).fillna(-1)
    selected = selected.sort_values(['l1_cap_yi', 'l2_cap_yi', 'cap_yi', 'ts_code'],
                                    ascending=[False, False, False, True], kind='mergesort')

    histories = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch_history, code, ts.pro_api(), prior_daily)
                   for code in selected.ts_code.astype(str)]
        for future in concurrent.futures.as_completed(futures):
            code, history = future.result()
            histories[code] = history

    prior_by_code = prior_basic.set_index('ts_code').to_dict('index')
    output = []
    addition_details = []
    for _, item in selected.iterrows():
        code = str(item.ts_code)
        old = existing.get(code)
        row = list(old) if old else [''] * len(HEADERS)
        if old is None:
            row[idx['名称']] = str(item.get('name') or item.get('name_basic') or item.get('name_x') or '')
            row[idx['笔记（AI别刷新这部分，我自己记录）']] = ''
            row[idx['申万一级']] = str(item.l1_name)
            row[idx['申万二级']] = str(item.l2_name)
            row[idx['代码']] = code
            description = str(item.get('main_business') or '').replace('\n', ' ').strip()
            row[idx['公司产品简介']] = '' if description == 'nan' else description[:180]
        row[idx['市值(亿元)']] = round(float(item.cap_yi), 1)
        prior = prior_by_code.get(code, {})
        prior_pe = number(prior.get('pe_ttm'))
        prior_close = number(prior.get('close'))
        current_price = number(item.get('price'))
        row[idx['PE(TTM)']] = (round(prior_pe * current_price / prior_close, 1)
                              if prior_pe is not None and prior_close and current_price is not None else '')
        row[idx['当日盘中实时涨幅%']] = round(float(item['pct_change']) / 100, 4)
        closes = histories[code].sort_values('trade_date').close.astype(float).tolist()
        closes.append(float(current_price))
        for days in PERIODS:
            row[idx[f'{days}日涨幅%']] = (round(closes[-1] / closes[-days - 1] - 1, 4)
                                          if len(closes) > days else '历史不足')
        output.append(row)
        if code in additions:
            qrow = qualified[qualified.ts_code.astype(str).eq(code)].iloc[0]
            peers = eligible[eligible.l2_code.eq(qrow.l2_code)].sort_values('cap_yi', ascending=False)
            rank = peers.ts_code.astype(str).tolist().index(code) + 1
            addition_details.append({
                'code': code, 'name': row[idx['名称']], 'market_cap_yi': round(float(item.cap_yi), 1),
                'sw_l1': row[idx['申万一级']], 'sw_l2': row[idx['申万二级']], 'l2_rank': rank,
                'reason': '市值超过600亿元' if item.cap_yi > 600 else '申万二级市值前二',
            })
    blank_rows = [[''] * len(HEADERS) for _ in range(len(before) - len(output) - 1)]
    values = [HEADERS] + output + blank_rows
    assert len(values) == len(before)
    save('payload.json', {'valueRange': {'range': f'{TARGET}!A1:Q{len(before)}', 'values': values}})
    save('summary.json', {
        'quote_time': stamp.strftime('%Y-%m-%d %H:%M:%S'),
        'title': f"实时数据（{stamp.strftime('%y.%m.%d %H')}点{stamp.strftime('%M')}分）",
        'existing': len(existing), 'added': len(additions), 'removed': 0,
        'final': len(output), 'additions': addition_details,
    })
    print(json.dumps(json.loads((WORK / 'summary.json').read_text()), ensure_ascii=False, indent=2))


def apply():
    token = feishu.get_token()
    before = json.loads((WORK / 'before.json').read_text())
    payload = json.loads((WORK / 'payload.json').read_text())
    values = payload['valueRange']['values']
    current = feishu.read_range(token, f'{TARGET}!A1:Q500')
    if current[1:] == values[1:] and current[0] == HEADERS:
        values[0] = HEADERS
    assert current in (before, values), 'Sheet changed after preparation'
    idx = {header: i for i, header in enumerate(HEADERS)}
    old_by_code = {str((list(row) + [''] * len(HEADERS))[idx['代码']]):
                   list(row) + [''] * (len(HEADERS) - len(row))
                   for row in before[1:] if row and row[0]}
    for row in values[1:]:
        if not row or not row[0] or str(row[idx['代码']]) not in old_by_code:
            continue
        old = old_by_code[str(row[idx['代码']])]
        assert row[:6] == old[:6]
    cf_before = json.loads((WORK / 'conditional_formats_before.json').read_text())
    filter_before = json.loads((WORK / 'filter_before.json').read_text())
    meta_before = json.loads((WORK / 'metadata_before.json').read_text())
    current_cf = feishu.condition_formats(token, TARGET)
    if any(TARGET + '!' not in range_name
           for entry in cf_before['data']['sheet_condition_formats']
           for range_name in entry['condition_format'].get('ranges', [])):
        cf_before = current_cf
        filter_before = feishu.sheet_filter(token, TARGET)
        meta_before = feishu.metadata(token, TARGET)
        save('conditional_formats_before.json', cf_before)
        save('filter_before.json', filter_before)
        save('metadata_before.json', meta_before)
    if current == before:
        feishu.api(feishu.BASE + '/values', token, method='PUT', body=payload)

    visible = [HEADERS] + [row for row in values[1:] if row and row[0]]
    mapping = ROOT / 'config/industry_color_map_20261012.json'
    industry_styles, industry_result = industry_style_payload(
        visible, TARGET, mapping, clear_to=500, l1_index=2, l2_index=3,
        column_count=len(HEADERS), excluded_columns={2})
    note_map = json.loads((ROOT / 'config/personal_note_colors_20261008.json').read_text())['codes']
    feishu.api(feishu.BASE + '/styles_batch_update', token, method='PUT',
               body={'data': style_payload(visible, industry_styles, note_map)})

    summary = json.loads((WORK / 'summary.json').read_text())
    if feishu.metadata(token, TARGET)['title'] != summary['title']:
        feishu.api(feishu.BASE + '/sheets_batch_update', token, method='POST', body={
            'requests': [{'updateSheet': {'properties': {
                'sheetId': TARGET, 'title': summary['title'],
            }}}],
        })

    after = feishu.read_range(token, f'{TARGET}!A1:Q500')
    for row_number, (expected, actual) in enumerate(zip(values, after), 1):
        expected = list(expected) + [''] * (len(HEADERS) - len(expected))
        actual = list(actual) + [''] * (len(HEADERS) - len(actual))
        assert expected == actual, row_number
    cf_after = feishu.condition_formats(token, TARGET)
    filter_after = feishu.sheet_filter(token, TARGET)
    meta_after = feishu.metadata(token, TARGET)
    assert cf_after == cf_before
    expected_filter_range = f"{TARGET}!A1:Q{summary['final'] + 1}"
    assert filter_after['data']['sheet_filter_info']['range'] == expected_filter_range
    assert not filter_after['data']['sheet_filter_info']['filtered_out_rows']
    assert meta_after['title'] == summary['title']
    for key in ('frozen_column_count', 'frozen_row_count', 'column_count', 'row_count'):
        assert meta_after['grid_properties'][key] == meta_before['grid_properties'][key]
    result = {
        **summary, 'sheet_id': TARGET,
        'url': 'https://my.feishu.cn/wiki/DlRmwrJOgiWIVhkWZtsc6h0Bnnd?sheet=' + TARGET,
        'updated_range': 'G:Q', 'existing_a_to_f_preserved_by_code': True,
        'values_verified': True,
        'conditional_formats': len(cf_after['data']['sheet_condition_formats']),
        'conditional_formats_preserved': True,
        'filter_range': expected_filter_range, 'all_rows_visible': True,
        'industry_colors': industry_result,
    }
    save('verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'prepare', 'apply'}:
        raise SystemExit('Usage: refresh_realtime_20261013.py prepare|apply')
    prepare() if sys.argv[1] == 'prepare' else apply()
