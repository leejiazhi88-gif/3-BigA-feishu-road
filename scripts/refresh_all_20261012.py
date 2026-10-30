#!/usr/bin/env python3
"""Refresh the 2026-10-12 copied all-stock sheet with 2026-10-09 data.

Selection is additive: retain every existing code and append any stock that is
over CNY 60bn or is needed for the top-two rule in its Shenwan L2 industry.
Personal notes and the Q3 archive column are preserved by stock code.
"""
from __future__ import annotations

import concurrent.futures
import copy
import json
import math
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import requests
import tushare as ts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work' / 'refresh-all-20261012'
RAW = WORK / 'raw'
WORK.mkdir(parents=True, exist_ok=True)
RAW.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))

import build_ai_chain_feishu as finance
import repair_quarter_profit_columns as quarter
import forecast_quality
from forecast_quality_sheet import apply_result as apply_quality_result
from supplement_forecast_reports import fetch as supplement_report
from business_composition import feishu_client as feishu
from industry_colors import style_payload as industry_style_payload

TARGET = 'avlLqL'
TITLE = '2026-10-12（全部）'
ASOF = '20261009'
ASOF_DISPLAY = '2026-10-09'
ANNUAL_CHANGE_HEADER = '本次刷新年度预测变化'
ANNUAL_CHANGE_RATE_HEADERS = {
    2026: '26年预测变化率',
    2027: '27年预测变化率',
    2028: '28年预测变化率',
}
DECISION_NOTE_HEADER = '笔记2 决策（AI也别刷新）'
PEAK_RETURN_HEADER = '360日内峰值距今涨幅%'
Q3_LOCK_HEADER = '2026 Q3净利润(亿元) 锁定比较基础'
LEGACY_Q3_LOCK_HEADER = '2026 Q3净利润(亿元) 复制备忘用，后续锁定比较基础'
Q3_NORMAL_HEADER = '2026Q3净利润(亿元)'
Q4_LOCK_HEADER = '2026Q4锁定预测(亿元)'
Q4_NORMAL_HEADER = '2026Q4净利润(亿元)'
PERIODS = (10, 30, 60, 90, 250, 360, 720, 1080)
REUSE_RAW = os.environ.get('REUSE_REFRESH_RAW') == '1'
INDUSTRY_COLOR_MAP = ROOT / 'config/industry_color_map_20261012.json'
PERSONAL_NOTE_STYLE_MAP = None
Q3_ROLLING_BASELINE_MAP = ROOT / 'config/q3_rolling_baselines_2026.json'
Q3_LOCKED_BASELINE_MAP = ROOT / 'config/q3_locked_baselines_2026.json'
EXPECTED_HEADERS = [
    '名称', '笔记（AI别刷新这部分，我自己记录）', '申万一级', '申万二级', '代码',
    '公司产品简介', '市值(亿元)', 'PE(TTM)', '2026 PE(预测)', '2027 PE(预测)',
    '2028 PE(预测)', '未来三年增速均值', '2025净利润(实际/预测,亿元)',
    '2026净利润(预测,亿元)', '2027净利润(预测,亿元)', '2028净利润(预测,亿元)',
    ANNUAL_CHANGE_HEADER,
    '2025净利润同比%(实际/预测)', '2026净利润同比%(预测)',
    '2027净利润同比%(预测)', '2028净利润同比%(预测)', '最新交易日', '当日涨幅%',
    '10日涨幅%', '30日涨幅%', '60日涨幅%', '90日涨幅%', '250日涨幅%',
    '360日涨幅%', '720日涨幅%', '1080日涨幅%', '预测来源', '数据状态', '备注',
    '2026Q1净利润(亿元)', '2026Q2锁定预测(亿元)', '2026Q2净利润(亿元)',
    Q3_LOCK_HEADER, '2026Q3净利润(亿元)',
    '2026Q4净利润(亿元)', '2027Q1净利润(亿元)', '2027Q2净利润(亿元)',
    '2027Q3净利润(亿元)', '2027Q4净利润(亿元)', '2028Q1净利润(亿元)',
    '2028Q2净利润(亿元)', '2028Q3净利润(亿元)', '2028Q4净利润(亿元)',
    '股息率%', '上财年全年股息率（25年·年日均市值）',
    '本财年预估全年股息率（26年）', '2026年股息率估算备注', '25年收入构成',
    '25年利润构成', '26年收入构成', '26年利润构成',
]


def validate_headers(headers):
    variants = []
    for q3_lock_header in (Q3_LOCK_HEADER, LEGACY_Q3_LOCK_HEADER):
        for include_decision_note in (False, True):
            for include_peak_return in (False, True):
                for include_q4_lock in (False, True):
                    for include_annual_rates in (False, True):
                        variant = list(EXPECTED_HEADERS)
                        variant[variant.index(Q3_LOCK_HEADER)] = q3_lock_header
                        if include_decision_note:
                            variant.insert(2, DECISION_NOTE_HEADER)
                        if include_annual_rates:
                            position = variant.index(ANNUAL_CHANGE_HEADER) + 1
                            for offset, header in enumerate(ANNUAL_CHANGE_RATE_HEADERS.values()):
                                variant.insert(position + offset, header)
                        if include_peak_return:
                            variant.insert(variant.index('360日涨幅%') + 1, PEAK_RETURN_HEADER)
                        if include_q4_lock:
                            variant.insert(variant.index(Q4_NORMAL_HEADER), Q4_LOCK_HEADER)
                        variants.append(variant)
    assert headers in variants, headers


def q3_lock_header(indices):
    return next(header for header in (Q3_LOCK_HEADER, LEGACY_Q3_LOCK_HEADER)
                if header in indices)


def sheet_range(headers, end_row=500):
    return f'{TARGET}!A1:{column_name(len(headers))}{end_row}'


def save(name, value):
    (WORK / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def query(pro, endpoint, **kwargs):
    for attempt in range(4):
        try:
            time.sleep(.18)
            return getattr(pro, endpoint)(**kwargs)
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 3:
                raise
            time.sleep(1 + attempt)


def number(value):
    if value in ('', None) or isinstance(value, bool):
        return None
    match = re.match(r'[-+]?\d+(?:\.\d+)?', str(value).strip())
    if not match:
        return None
    result = float(match.group())
    return result if math.isfinite(result) else None


def fmt_number(value):
    return finance.fmt_num(value)


def fmt_pct_fraction(value):
    return '' if value is None or not math.isfinite(float(value)) else round(float(value), 3)


def code_file(code):
    return code.replace('.', '_')


def fetch_market(pro):
    if REUSE_RAW and (RAW / f'daily_basic_{ASOF}.csv').exists():
        return (pd.read_csv(RAW / f'daily_basic_{ASOF}.csv', dtype={'trade_date': str}),
                pd.read_csv(RAW / 'stock_basic.csv'),
                pd.read_csv(RAW / 'stock_company.csv'))
    daily = query(pro, 'daily_basic', trade_date=ASOF,
                  fields='ts_code,trade_date,close,pe_ttm,dv_ttm,total_mv,total_share')
    assert len(daily) > 5000 and daily.trade_date.astype(str).eq(ASOF).all()
    stocks = query(pro, 'stock_basic', exchange='', list_status='L',
                   fields='ts_code,symbol,name,area,industry,market,list_date')
    companies = []
    for exchange in ('SSE', 'SZSE', 'BSE'):
        companies.append(query(pro, 'stock_company', exchange=exchange,
                               fields='ts_code,exchange,main_business'))
    company = pd.concat(companies, ignore_index=True).drop_duplicates('ts_code')
    daily.to_csv(RAW / f'daily_basic_{ASOF}.csv', index=False)
    stocks.to_csv(RAW / 'stock_basic.csv', index=False)
    company.to_csv(RAW / 'stock_company.csv', index=False)
    return daily, stocks, company


def fetch_industries(pro):
    if REUSE_RAW and (RAW / 'industry_members.csv').exists():
        return pd.read_csv(RAW / 'industry_members.csv')
    l1 = query(pro, 'index_classify', level='L1', src='SW2021',
               fields='index_code,industry_name,level,industry_code,parent_code,is_pub')
    l2 = query(pro, 'index_classify', level='L2', src='SW2021',
               fields='index_code,industry_name,level,industry_code,parent_code,is_pub')
    frames = []
    for code in l1.index_code.dropna().astype(str):
        frame = query(pro, 'index_member_all', l1_code=code, is_new='Y',
                      fields='l1_code,l2_code,l2_name,ts_code,name,in_date,out_date,is_new')
        if not frame.empty:
            frames.append(frame)
    members = pd.concat(frames, ignore_index=True)
    members = members[members.is_new.astype(str).eq('Y')]
    members = members.sort_values(['ts_code', 'in_date']).drop_duplicates('ts_code', keep='last')
    members['l1_name'] = members.l1_code.map(l1.set_index('index_code').industry_name)
    members['l2_name'] = members.l2_code.map(l2.set_index('index_code').industry_name).fillna(members.l2_name)
    members.to_csv(RAW / 'industry_members.csv', index=False)
    return members


def fetch_price(code, pro):
    path = RAW / 'prices' / f'{code_file(code)}.csv'
    path.parent.mkdir(exist_ok=True)
    if REUSE_RAW and path.exists():
        return code
    frame = query(pro, 'daily', ts_code=code, start_date='20220101', end_date=ASOF,
                  fields='ts_code,trade_date,close,pct_chg')
    assert not frame.empty and str(frame.trade_date.astype(str).max()) == ASOF, code
    frame.to_csv(path, index=False)
    return code


def fetch_fundamentals(code, pro):
    specs = {
        'income': ('income', dict(
            ts_code=code, start_date='20230101', end_date=ASOF,
            fields='ts_code,ann_date,f_ann_date,end_date,report_type,n_income_attr_p')),
        'report_rc': ('report_rc', dict(ts_code=code, start_date='20250101', end_date=ASOF)),
    }
    result = {'code': code}
    for folder, (endpoint, kwargs) in specs.items():
        path = RAW / folder / f'{code_file(code)}.csv'
        path.parent.mkdir(exist_ok=True)
        if REUSE_RAW and path.exists():
            frame = pd.read_csv(path)
        else:
            frame = query(pro, endpoint, **kwargs)
            frame.to_csv(path, index=False)
        result[folder] = len(frame)
    return result


def read_csv(folder, code):
    path = RAW / folder / f'{code_file(code)}.csv'
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    dtype = {'trade_date': str, 'end_date': str, 'ann_date': str,
             'f_ann_date': str, 'report_date': str, 'quarter': str}
    return pd.read_csv(path, dtype=dtype)


def return_value(history, days):
    history = history.sort_values('trade_date').drop_duplicates('trade_date', keep='last')
    if len(history) <= days:
        return None
    return float(history.iloc[-1].close / history.iloc[-days - 1].close - 1)


def peak_return_value(history, days=360):
    history = history.sort_values('trade_date').drop_duplicates('trade_date', keep='last')
    if history.empty:
        return None
    window_size = min(days, len(history))
    window = pd.to_numeric(history.iloc[-window_size:].close, errors='coerce').dropna()
    if len(window) != window_size or window.max() <= 0:
        return None
    return float(window.iloc[-1] / window.max() - 1)


def annotate_actual(actual, locked, label='锁定预测', show_missing=False):
    if actual is None:
        return ''
    value = fmt_number(actual)
    prior = number(locked)
    if prior is not None:
        return f'{value}（{label}{prior:.1f}）'
    return f'{value}（{label}无）' if show_missing else value


def prior_forecast(cell):
    match = re.search(
        r'（(?:上个Q预测|锁定预测|未锁定预测)([-+]?\d+(?:\.\d+)?)）',
        str(cell or ''),
    )
    return number(match.group(1)) if match else None


def comparison_forecast(cell):
    return prior_forecast(cell) if '（' in str(cell or '') else number(cell)


def q3_rolling_forecast(code, cell):
    if Q3_ROLLING_BASELINE_MAP.exists() and code:
        archive = json.loads(Q3_ROLLING_BASELINE_MAP.read_text())
        entry = archive.get(str(code))
        if entry:
            return number(entry.get('baseline'))
    match = re.search(
        r'（(上个Q预测|锁定预测|未锁定预测)([-+]?\d+(?:\.\d+)?)）',
        str(cell or ''),
    )
    if not match:
        return number(cell)
    label, value = match.groups()
    if label != '锁定预测':
        return number(value)
    return None


def q3_locked_forecast(code, cell):
    if '（' in str(cell or ''):
        return prior_forecast(cell)
    if Q3_LOCKED_BASELINE_MAP.exists() and code:
        archive = json.loads(Q3_LOCKED_BASELINE_MAP.read_text())
        if str(code) in archive:
            return number(archive[str(code)].get('baseline'))
    return number(cell)


def quarterly_values(row, idx, income, annual, code=None):
    actuals = finance.actual_quarter_profit_yi(income)
    weights = quarter.quarter_weights(income)
    quarter_annual = dict(annual)
    if quarter_annual.get(2026) is None:
        quarter_annual[2026] = (quarter.annualize_h1(actuals, weights)
                                or quarter.latest_historical_annual(actuals))
    for year in (2027, 2028):
        if quarter_annual.get(year) is None:
            quarter_annual[year] = quarter_annual.get(year - 1)
    result = {}
    result['2026Q1净利润(亿元)'] = annotate_actual(
        actuals.get('2026Q1'), prior_forecast(row[idx['2026Q1净利润(亿元)']]), '上个Q预测')
    result['2026Q2净利润(亿元)'] = annotate_actual(
        actuals.get('2026Q2'), prior_forecast(row[idx['2026Q2净利润(亿元)']]), '上个Q预测')
    q3_actual = actuals.get('2026Q3')
    locked_header = q3_lock_header(idx)
    q3_locked = row[idx[locked_header]]
    q3_normal = row[idx[Q3_NORMAL_HEADER]]
    if q3_actual is not None:
        result[locked_header] = annotate_actual(
            q3_actual, q3_locked_forecast(code, q3_locked), '锁定预测', show_missing=True)
        result[Q3_NORMAL_HEADER] = annotate_actual(
            q3_actual, q3_rolling_forecast(code, q3_normal), '未锁定预测')
    else:
        used = sum(v for v in (actuals.get('2026Q1'), actuals.get('2026Q2')) if v is not None)
        remainder = quarter_annual[2026] - used if quarter_annual.get(2026) is not None else None
        denom = weights[3] + weights[4]
        result[Q3_NORMAL_HEADER] = fmt_number(remainder * weights[3] / denom) if remainder is not None and denom else ''
    used = sum(v for v in (actuals.get('2026Q1'), actuals.get('2026Q2'), q3_actual) if v is not None)
    q4_actual = actuals.get('2026Q4')
    if q4_actual is not None:
        if Q4_LOCK_HEADER in idx:
            result[Q4_LOCK_HEADER] = annotate_actual(
                q4_actual, comparison_forecast(row[idx[Q4_LOCK_HEADER]]), '锁定预测',
                show_missing=True)
        result[Q4_NORMAL_HEADER] = annotate_actual(
            q4_actual, comparison_forecast(row[idx[Q4_NORMAL_HEADER]]), '未锁定预测')
    elif quarter_annual.get(2026) is None:
        result[Q4_NORMAL_HEADER] = ''
    elif q3_actual is not None:
        result[Q4_NORMAL_HEADER] = fmt_number(quarter_annual[2026] - used)
    else:
        remainder = quarter_annual[2026] - used
        denom = weights[3] + weights[4]
        result[Q4_NORMAL_HEADER] = fmt_number(remainder * weights[4] / denom) if denom else ''
    for year in (2027, 2028):
        parts = (quarter.split_annual(quarter_annual[year], weights)
                 if quarter_annual.get(year) is not None else [''] * 4)
        for q, value in enumerate(parts, 1):
            result[f'{year}Q{q}净利润(亿元)'] = value
    return result


def percent_change(old, new):
    old_num, new_num = number(old), number(new)
    if old_num is None or new_num is None or abs(old_num) < 1e-12:
        return None
    return (new_num - old_num) / abs(old_num)


def make_changes(code, name, old_row, new_row, idx):
    fields = [f'{year}净利润(预测,亿元)' for year in (2026, 2027, 2028)]
    fields += ['2026Q3净利润(亿元)', '2026Q4净利润(亿元)']
    fields += [f'{year}Q{q}净利润(亿元)' for year in (2027, 2028) for q in range(1, 5)]
    changes = []
    for field in fields:
        old, new = old_row[idx[field]], new_row[idx[field]]
        old_num, new_num = number(old), number(new)
        if old_num is None and new_num is None:
            continue
        if old_num is not None and new_num is not None and math.isclose(old_num, new_num, abs_tol=.05):
            continue
        changes.append({'code': code, 'name': name, 'field': field, 'old': old,
                        'new': new, 'change_ratio': percent_change(old, new)})
    return changes


def annual_change_text(changes):
    parts = []
    for change in changes:
        match = re.match(r'(20\d{2})净利润\(预测,亿元\)', change['field'])
        if not match:
            continue
        year = match.group(1)
        old = change['old']
        ratio = change['change_ratio']
        if number(old) is None or ratio is None:
            parts.append(f'{year}年（旧值无，新增预测）')
        else:
            parts.append(f'{year}年（旧值{fmt_number(number(old))}，{ratio:+.1%}）')
    return '；'.join(parts)


def annual_change_color_from_text(text):
    matches = re.findall(
        r'(20\d{2})年（旧值[^，]*，(新增预测|[-+]?\d+(?:\.\d+)?%)）',
        str(text or ''),
    )
    if not matches:
        return '#000000'
    _, movement = min(matches, key=lambda item: int(item[0]))
    if movement == '新增预测':
        return '#000000'
    ratio = float(movement.rstrip('%'))
    return '#00B050' if ratio > 0 else '#C00000' if ratio < 0 else '#000000'


def annual_change_rates_from_text(text):
    rates = {year: '' for year in ANNUAL_CHANGE_RATE_HEADERS}
    matches = re.findall(
        r'(20\d{2})年（旧值[^，]*，(新增预测|[-+]?\d+(?:\.\d+)?%)）',
        str(text or ''),
    )
    for year_text, movement in matches:
        year = int(year_text)
        if year in rates and movement != '新增预测':
            rates[year] = round(float(movement.rstrip('%')) / 100, 6)
    return rates


def annual_change_rate_style_payload(values):
    headers = values[0]
    idx = {header: i for i, header in enumerate(headers)}
    groups = {}
    for row_number, row in enumerate(values[1:], 2):
        if not row or not row[0]:
            continue
        row = list(row) + [''] * (len(headers) - len(row))
        for header in ANNUAL_CHANGE_RATE_HEADERS.values():
            if header not in idx:
                continue
            value = number(row[idx[header]])
            color = ('#000000' if value is None or value == 0
                     else '#00B050' if value > 0 else '#C00000')
            groups.setdefault(color, []).append(
                f'{TARGET}!{column_name(idx[header] + 1)}{row_number}:'
                f'{column_name(idx[header] + 1)}{row_number}')
    styles = []
    for color, ranges in groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({
                'ranges': ranges[start:start + 100],
                'style': {'foreColor': color, 'formatter': '0.00%'},
            })
    return styles


def annual_change_style_payload(values, changes=None):
    headers = values[0]
    idx = {header: i for i, header in enumerate(headers)}
    groups = {}
    for row_number, row in enumerate(values[1:], 2):
        if not row or not row[0]:
            continue
        row = list(row) + [''] * (len(headers) - len(row))
        color = annual_change_color_from_text(row[idx[ANNUAL_CHANGE_HEADER]])
        groups.setdefault(color, []).append(
            f'{TARGET}!{column_name(idx[ANNUAL_CHANGE_HEADER] + 1)}{row_number}:'
            f'{column_name(idx[ANNUAL_CHANGE_HEADER] + 1)}{row_number}')
    styles = []
    for color, ranges in groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({'ranges': ranges[start:start + 100],
                           'style': {'foreColor': color}})
    return styles


def column_name(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def append_and_move_column(token, destination_index):
    metadata = feishu.metadata(token, TARGET)
    old_count = metadata['grid_properties']['column_count']
    feishu.api(feishu.BASE + '/dimension_range', token, 'POST', {
        'dimension': {'sheetId': TARGET, 'majorDimension': 'COLUMNS', 'length': 1},
    })
    feishu.api(
        f'sheets/v3/spreadsheets/{feishu.SPREADSHEET}/sheets/{TARGET}/move_dimension',
        token, 'POST', {
            'source': {'major_dimension': 'COLUMNS', 'start_index': old_count,
                       'end_index': old_count},
            'destination_index': destination_index,
        },
    )


def shifted_column_name(name, insertion_index):
    value = 0
    for char in name:
        value = value * 26 + ord(char) - ord('A') + 1
    if value - 1 >= insertion_index:
        value += 1
    return column_name(value)


def shifted_range(address, insertion_index):
    if not isinstance(address, str) or '!' not in address:
        return address
    sheet, cells = address.split('!', 1)

    def replace(match):
        absolute, letters = match.groups()
        return absolute + shifted_column_name(letters, insertion_index)

    cells = re.sub(r'(?<![A-Z])([$]?)([A-Z]+)(?=[$]?\d)', replace, cells)
    return sheet + '!' + cells


def shifted_range_payload(value, insertion_index):
    if isinstance(value, dict):
        return {key: shifted_range_payload(item, insertion_index)
                for key, item in value.items()}
    if isinstance(value, list):
        return [shifted_range_payload(item, insertion_index) for item in value]
    return shifted_range(value, insertion_index)


def font_style_payload(values):
    headers, rows = values[0], values[1:]
    idx = {header: i for i, header in enumerate(headers)}
    pattern = re.compile(
        r'([-+]?\d+(?:\.\d+)?)（(?:上个Q预测|锁定预测|未锁定预测)'
        r'([-+]?\d+(?:\.\d+)?)）')
    groups = {}

    def add(row_number, header, color):
        cell = f'{column_name(idx[header] + 1)}{row_number}'
        groups.setdefault(color, []).append(f'{TARGET}!{cell}:{cell}')

    pe_headers = ['PE(TTM)', '2026 PE(预测)', '2027 PE(预测)', '2028 PE(预测)']
    yoy_headers = ['2025净利润同比%(实际/预测)', '2026净利润同比%(预测)',
                   '2027净利润同比%(预测)', '2028净利润同比%(预测)']
    actual_headers = [
        header for header in (
            '2026Q1净利润(亿元)', '2026Q2锁定预测(亿元)', '2026Q2净利润(亿元)',
            q3_lock_header(idx), Q3_NORMAL_HEADER, Q4_LOCK_HEADER, Q4_NORMAL_HEADER,
        ) if header in idx
    ]
    for row_number, row in enumerate(rows, 2):
        row = list(row) + [''] * (len(headers) - len(row))
        for header in pe_headers:
            value = number(row[idx[header]])
            add(row_number, header, '#00B050' if value is not None and value < 30
                else '#C00000' if value is not None and value > 50 else '#000000')
        for header in yoy_headers:
            value = number(row[idx[header]])
            add(row_number, header, '#C00000' if value is not None and value <= 0
                else '#00B050' if value is not None and value >= .30
                else '#0070C0' if value is not None and value >= .10 else '#000000')
        for header in actual_headers:
            match = pattern.search(str(row[idx[header]] or ''))
            color = '#000000'
            if match:
                actual, forecast = map(float, match.groups())
                ratio = ((actual - forecast) / abs(forecast) if forecast else
                         (0 if abs(actual) <= .05 else math.copysign(1, actual)))
                color = '#0070C0' if abs(ratio) <= .10 else '#00B050' if ratio > .10 else '#C00000'
            add(row_number, header, color)
    styles = []
    for color, ranges in groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({'ranges': ranges[start:start + 100],
                           'style': {'foreColor': color}})
    return styles


def personal_note_style_payload(values):
    path = PERSONAL_NOTE_STYLE_MAP or WORK / 'personal_note_styles.json'
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    saved = data.get('codes', data)
    headers = values[0]
    idx = {header: i for i, header in enumerate(headers)}
    note_headers = [h for h in (
        '笔记（AI别刷新这部分，我自己记录）', DECISION_NOTE_HEADER,
    ) if h in idx]
    groups = {}
    for row_number, row in enumerate(values[1:], 2):
        if not row or not row[0]:
            continue
        row = list(row) + [''] * (len(headers) - len(row))
        code = str(row[idx['代码']])
        for header in note_headers:
            style = saved.get(code, {}).get(header, {
                'backColor': '#FFFFFF', 'foreColor': '#000000',
            })
            key = (style['backColor'], style['foreColor'])
            cell = f'{column_name(idx[header] + 1)}{row_number}'
            groups.setdefault(key, []).append(f'{TARGET}!{cell}:{cell}')
    result = []
    for (back_color, fore_color), ranges in groups.items():
        for start in range(0, len(ranges), 100):
            result.append({
                'ranges': ranges[start:start + 100],
                'style': {'backColor': back_color, 'foreColor': fore_color},
            })
    return result


def prepare():
    token = feishu.get_token()
    metadata = feishu.metadata(token, TARGET)
    column_count = metadata['grid_properties']['column_count']
    before = feishu.read_range(token, f'{TARGET}!A1:{column_name(column_count)}500')
    headers = before[0]
    validate_headers(headers)
    rows = [list(row) + [''] * (len(headers) - len(row)) for row in before[1:] if row and row[0]]
    assert len(rows) >= 446
    idx = {header: i for i, header in enumerate(headers)}
    existing = {str(row[idx['代码']]): row for row in rows}
    assert len(existing) == len(rows)
    save('before.json', before)
    save('cf_before.json', feishu.condition_formats(token, TARGET))
    save('filter_before.json', feishu.sheet_filter(token, TARGET))
    save('metadata_before.json', metadata)

    pro = ts.pro_api(os.environ.get('TUSHARE_TOKEN')) if os.environ.get('TUSHARE_TOKEN') else ts.pro_api()
    daily, stocks, companies = fetch_market(pro)
    members = fetch_industries(pro)
    market = daily.merge(stocks[['ts_code', 'name']], on='ts_code', how='left')
    market = market.merge(companies[['ts_code', 'main_business']], on='ts_code', how='left')
    market = market.merge(members[['ts_code', 'l1_code', 'l2_code', 'l1_name', 'l2_name']], on='ts_code', how='left')
    market['cap_yi'] = pd.to_numeric(market.total_mv, errors='coerce') / 10000
    eligible = market.dropna(subset=['l1_code', 'l2_code', 'l1_name', 'l2_name']).copy()
    threshold = eligible[eligible.cap_yi > 600]
    top2 = (eligible.sort_values(['l2_code', 'cap_yi', 'ts_code'], ascending=[True, False, True])
            .groupby('l2_code', sort=False).head(2))
    qualified = pd.concat([threshold, top2]).drop_duplicates('ts_code')
    additions = sorted(set(qualified.ts_code.astype(str)) - set(existing))
    retained_missing_market = sorted(set(existing) - set(market.ts_code.astype(str)))
    assert not retained_missing_market, retained_missing_market
    selected = market[market.ts_code.astype(str).isin(set(existing) | set(additions))].copy()
    l1_cap = eligible.groupby('l1_code').cap_yi.sum().to_dict()
    l2_cap = eligible.groupby('l2_code').cap_yi.sum().to_dict()
    selected['l1_cap_yi'] = selected.l1_code.map(l1_cap).fillna(-1)
    selected['l2_cap_yi'] = selected.l2_code.map(l2_cap).fillna(-1)
    selected = selected.sort_values(['l1_cap_yi', 'l2_cap_yi', 'cap_yi', 'ts_code'],
                                    ascending=[False, False, False, True], kind='mergesort')
    codes = selected.ts_code.astype(str).tolist()
    assert set(codes) == set(existing) | set(additions)

    print(json.dumps({'existing': len(existing), 'additions': len(additions),
                      'final': len(codes)}, ensure_ascii=False), flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch_price, code, ts.pro_api()) for code in codes]
        for n, future in enumerate(concurrent.futures.as_completed(futures), 1):
            future.result()
            if n % 50 == 0 or n == len(futures):
                print(f'prices {n}/{len(futures)}', flush=True)
    fundamental_log = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(fetch_fundamentals, code, ts.pro_api()) for code in codes]
        for n, future in enumerate(concurrent.futures.as_completed(futures), 1):
            fundamental_log.append(future.result())
            if n % 50 == 0 or n == len(futures):
                print(f'fundamentals {n}/{len(futures)}', flush=True)
    save('fundamental_fetch.json', fundamental_log)
    finance.RAW_DIR = RAW
    quarter.RAW_DIR = RAW

    composition_by_code = {
        x['code']: x['values'] for x in json.loads(
            (ROOT / 'exports/business_composition/2026-10-08-all.json').read_text())
    }
    output_rows, changes, addition_details = [], [], []
    quality_audits = []
    q3_actual_count = q4_actual_count = 0
    for _, item in selected.iterrows():
        code = str(item.ts_code)
        old_row = copy.deepcopy(existing.get(code, [''] * len(headers)))
        row = copy.deepcopy(old_row)
        name = str(item['name'])
        row[idx['名称']] = name
        if code not in existing:
            row[idx['笔记（AI别刷新这部分，我自己记录）']] = ''
            if DECISION_NOTE_HEADER in idx:
                row[idx[DECISION_NOTE_HEADER]] = ''
            row[idx[q3_lock_header(idx)]] = ''
            description = str(item.get('main_business') or '').replace('\n', ' ').strip()
            row[idx['公司产品简介']] = '' if description == 'nan' else description[:180]
            if code in composition_by_code:
                for header, value in zip(EXPECTED_HEADERS[-4:], composition_by_code[code]):
                    row[idx[header]] = value
        l1_name = item.get('l1_name')
        l2_name = item.get('l2_name')
        if pd.isna(l1_name) or str(l1_name).strip().lower() == 'nan':
            l1_name = row[idx['申万一级']]
        if pd.isna(l2_name) or str(l2_name).strip().lower() == 'nan':
            l2_name = row[idx['申万二级']]
        row[idx['申万一级']] = str(l1_name)
        row[idx['申万二级']] = str(l2_name)
        row[idx['代码']] = code
        cap = float(item.cap_yi)
        row[idx['市值(亿元)']] = round(cap, 1)
        row[idx['PE(TTM)']] = fmt_number(item.get('pe_ttm'))
        row[idx['最新交易日']] = ASOF_DISPLAY
        history = read_csv('prices', code).sort_values('trade_date')
        latest = history.iloc[-1]
        row[idx['当日涨幅%']] = fmt_pct_fraction(float(latest.pct_chg) / 100)
        for days in PERIODS:
            value = return_value(history, days)
            row[idx[f'{days}日涨幅%']] = fmt_pct_fraction(value) if value is not None else '历史不足'
        if PEAK_RETURN_HEADER in idx:
            value = peak_return_value(history)
            row[idx[PEAK_RETURN_HEADER]] = fmt_pct_fraction(value) if value is not None else '历史不足'
        dv = number(item.get('dv_ttm'))
        row[idx['股息率%']] = round(dv / 100, 6) if dv is not None else ''

        income, report = read_csv('income', code), read_csv('report_rc', code)
        quarter_actuals = finance.actual_quarter_profit_yi(income)
        if quarter_actuals.get('2026Q3') is not None:
            q3_actual_count += 1
        if quarter_actuals.get('2026Q4') is not None:
            q4_actual_count += 1
        profits, yoy, pes, provenance = finance.profit_cells(report, income, cap)
        annual = {year: number(profits[year]) for year in (2025, 2026, 2027, 2028)}
        for year in (2025, 2026, 2027, 2028):
            ph = f'{year}净利润(实际/预测,亿元)' if year == 2025 else f'{year}净利润(预测,亿元)'
            yh = f'{year}净利润同比%(实际/预测)' if year == 2025 else f'{year}净利润同比%(预测)'
            row[idx[ph]] = profits[year]
            row[idx[yh]] = yoy[year]
            if year != 2025:
                row[idx[f'{year} PE(预测)']] = pes[year]
        growth = [number(yoy[y]) for y in (2026, 2027, 2028)]
        row[idx['未来三年增速均值']] = sum(growth) / len(growth) if all(x is not None for x in growth) else ''
        row[idx['预测来源']] = provenance
        missing = [str(y) for y in (2026, 2027, 2028) if annual[y] is None]
        row[idx['数据状态']] = '缺预测：' + ','.join(missing) if missing else 'OK'
        for header, value in quarterly_values(row, idx, income, annual, code).items():
            row[idx[header]] = value
        quality_result, needs_external = forecast_quality.build(
            report, income, ASOF, str(l2_name), annual.get(2025))
        external_check = None
        if needs_external:
            external_check = supplement_report({'code': code, 'name': name}, ASOF, WORK / 'external')
            if external_check['records']:
                augmented = pd.concat([report, pd.DataFrame(external_check['records'])], ignore_index=True)
                quality_result, _ = forecast_quality.build(
                    augmented, income, ASOF, str(l2_name), annual.get(2025))
        apply_quality_result(row, idx, quality_result)
        if external_check and external_check['status'] != 'ok':
            row[idx['数据状态']] += '；外部补查失败，未视为无更新'
        quality_audits.append({'code': code, 'name': name, 'years': quality_result,
                               'external_check': external_check})
        if code not in existing and Q4_LOCK_HEADER in idx and quarter_actuals.get('2026Q4') is None:
            row[idx[Q4_LOCK_HEADER]] = row[idx[Q4_NORMAL_HEADER]]

        old_cap = number(old_row[idx['市值(亿元)']]) if code in existing else None
        old_yield = number(old_row[idx['本财年预估全年股息率（26年）']]) if code in existing else None
        if old_yield is not None and old_cap and cap > 0:
            row[idx['本财年预估全年股息率（26年）']] = old_yield * old_cap / cap
        row_changes = make_changes(code, name, old_row, row, idx) if code in existing else []
        row[idx[ANNUAL_CHANGE_HEADER]] = annual_change_text(row_changes)
        annual_rates = annual_change_rates_from_text(row[idx[ANNUAL_CHANGE_HEADER]])
        for year, header in ANNUAL_CHANGE_RATE_HEADERS.items():
            if header in idx:
                row[idx[header]] = annual_rates[year]
        changes.extend(row_changes)
        if code in additions:
            qualified_row = qualified[qualified.ts_code.astype(str).eq(code)].iloc[0]
            l2_peers = eligible[eligible.l2_code.eq(qualified_row.l2_code)].sort_values('cap_yi', ascending=False)
            rank = int(l2_peers.ts_code.astype(str).tolist().index(code) + 1)
            addition_details.append({'code': code, 'name': name, 'market_cap_yi': round(cap, 1),
                                     'sw_l1': row[idx['申万一级']], 'sw_l2': row[idx['申万二级']],
                                     'l2_rank': rank,
                                     'reason': '市值超过600亿元' if cap > 600 else '申万二级市值前二'})
        output_rows.append(row)

    q3_actual_complete = bool(output_rows) and q3_actual_count == len(output_rows)
    if q3_actual_complete and Q4_LOCK_HEADER not in headers and q4_actual_count:
        raise RuntimeError('Cannot create a valid Q4 lock after Q4 actuals have started')
    q4_lock_column_inserted = q3_actual_complete and Q4_LOCK_HEADER not in headers
    if q4_lock_column_inserted:
        q4_index = headers.index(Q4_NORMAL_HEADER)
        headers.insert(q4_index, Q4_LOCK_HEADER)
        for row in output_rows:
            row.insert(q4_index, copy.deepcopy(row[q4_index]))

    payload = [headers] + output_rows + [[''] * len(headers) for _ in range(len(before) - len(output_rows) - 1)]
    assert len(payload) == len(before)
    save('payload.json', {'valueRange': {'range': sheet_range(headers, len(before)), 'values': payload}})
    save('forecast_changes.json', changes)
    save('forecast_quality_audit.json', quality_audits)
    save('additions.json', addition_details)
    save('summary.json', {'asof': ASOF_DISPLAY, 'existing': len(existing), 'added': len(additions),
                          'removed': 0, 'final': len(output_rows), 'additions': addition_details,
                          'forecast_changes': len(changes),
                          'q3_actual_count': q3_actual_count,
                          'q3_actual_complete': q3_actual_complete,
                          'q4_actual_count': q4_actual_count,
                          'q4_lock_column_inserted': q4_lock_column_inserted})


def equivalent(a, b):
    if a in ('', None) and b in ('', None):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(float(a), float(b), rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def apply():
    token = feishu.get_token()
    before = json.loads((WORK / 'before.json').read_text())
    current = feishu.read_range(token, sheet_range(before[0]))
    assert current == before, 'Sheet changed after preparation'
    payload = json.loads((WORK / 'payload.json').read_text())
    values = payload['valueRange']['values']
    headers, idx = values[0], {h: i for i, h in enumerate(values[0])}
    width = len(headers)
    old_headers = before[0]
    old_idx = {h: i for i, h in enumerate(old_headers)}
    old_width = len(old_headers)
    old_by_code = {str((list(r) + [''] * old_width)[old_idx['代码']]):
                   list(r) + [''] * (old_width-len(r))
                   for r in before[1:] if r and r[0]}
    for row in values[1:]:
        if not row or not row[0] or str(row[idx['代码']]) not in old_by_code:
            continue
        old = old_by_code[str(row[idx['代码']])]
        note_header = '笔记（AI别刷新这部分，我自己记录）'
        assert row[idx[note_header]] == old[old_idx[note_header]]
        if DECISION_NOTE_HEADER in idx and DECISION_NOTE_HEADER in old_idx:
            assert row[idx[DECISION_NOTE_HEADER]] == old[old_idx[DECISION_NOTE_HEADER]]
        new_q3_lock_header = q3_lock_header(idx)
        old_q3_lock_header = q3_lock_header(old_idx)
        if row[idx[new_q3_lock_header]] != old[old_idx[old_q3_lock_header]]:
            assert '（锁定预测' in str(row[idx[new_q3_lock_header]])
        for header in ('25年收入构成', '25年利润构成', '26年收入构成', '26年利润构成'):
            assert row[idx[header]] == old[old_idx[header]]
    cf_before = json.loads((WORK / 'cf_before.json').read_text())
    filter_before = json.loads((WORK / 'filter_before.json').read_text())
    meta_before = json.loads((WORK / 'metadata_before.json').read_text())
    summary = json.loads((WORK / 'summary.json').read_text())
    if summary['q4_lock_column_inserted']:
        append_and_move_column(token, idx[Q4_LOCK_HEADER])
    feishu.api(feishu.BASE + '/values', token, 'PUT', payload)

    visible = [values[0]] + [row for row in values[1:] if row and row[0]]
    feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT',
               {'data': font_style_payload(visible)})
    mapping = INDUSTRY_COLOR_MAP
    note_columns = {
        idx[header] + 1 for header in (
            '笔记（AI别刷新这部分，我自己记录）', DECISION_NOTE_HEADER,
        ) if header in idx
    }
    industry_styles, industry_result = industry_style_payload(
        visible, TARGET, mapping, clear_to=500,
        l1_index=idx['申万一级'], l2_index=idx['申万二级'],
        column_count=len(headers), excluded_columns=note_columns)
    feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT', {'data': industry_styles})
    note_styles = personal_note_style_payload(visible)
    if note_styles:
        feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT', {'data': note_styles})
    changes = json.loads((WORK / 'forecast_changes.json').read_text())
    feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT',
               {'data': annual_change_style_payload(visible, changes)})
    annual_rate_styles = annual_change_rate_style_payload(visible)
    if annual_rate_styles:
        feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT',
                   {'data': annual_rate_styles})

    after = feishu.read_range(token, sheet_range(headers))
    for rn, (expected, actual) in enumerate(zip(values, after), 1):
        expected = list(expected) + [''] * (width-len(expected))
        actual = list(actual) + [''] * (width-len(actual))
        for cn, (a, b) in enumerate(zip(expected, actual), 1):
            assert equivalent(a, b), (rn, cn, a, b)
    cf_after = feishu.condition_formats(token, TARGET)
    filter_after = feishu.sheet_filter(token, TARGET)
    meta_after = feishu.metadata(token, TARGET)
    if summary['q4_lock_column_inserted']:
        insertion_index = idx[Q4_LOCK_HEADER]
        assert cf_after == shifted_range_payload(cf_before, insertion_index)
        assert filter_after == shifted_range_payload(filter_before, insertion_index)
    else:
        assert cf_after == cf_before and filter_after == filter_before
    for key in ('frozen_column_count', 'frozen_row_count', 'column_count', 'row_count'):
        expected = meta_before['grid_properties'][key]
        if key == 'column_count' and summary['q4_lock_column_inserted']:
            expected += 1
        assert meta_after['grid_properties'][key] == expected
    result = {**summary, 'sheet_id': TARGET,
              'url': 'https://my.feishu.cn/wiki/DlRmwrJOgiWIVhkWZtsc6h0Bnnd?sheet=' + TARGET,
              'values_verified': True, 'conditional_formats': len(cf_after['data']['sheet_condition_formats']),
              'conditional_formats_preserved': True, 'filter_preserved': True,
              'notes_preserved': True, 'decision_notes_preserved': DECISION_NOTE_HEADER in idx,
              'personal_note_styles_restored_by_code': bool(note_styles),
              'q3_locked_comparison_rows': summary['q3_actual_count'],
              'q4_lock_column_ready': Q4_LOCK_HEADER in idx,
              'composition_preserved_for_existing': True, 'industry_colors': industry_result}
    save('verification.json', result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'prepare', 'apply'}:
        raise SystemExit('Usage: refresh_all_20261012.py prepare|apply')
    prepare() if sys.argv[1] == 'prepare' else apply()
