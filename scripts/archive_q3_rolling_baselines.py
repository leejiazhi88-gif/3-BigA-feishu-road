#!/usr/bin/env python3
"""Recover each company's last rolling Q3 forecast before its Q3 announcement."""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))

import refresh_all_20261012 as worker
from business_composition import feishu_client as feishu

OUTPUT = ROOT / 'config' / 'q3_rolling_baselines_2026.json'
worker.RAW = ROOT / 'work' / 'refresh-all-20261023' / 'raw'


def sheet_date(title):
    match = re.match(r'(2026)-(\d{1,2})-(\d{1,2})', title)
    return datetime(*map(int, match.groups())).strftime('%Y%m%d') if match else None


def announcement_date(code):
    income = worker.read_csv('income', code)
    if income.empty or 'end_date' not in income.columns:
        return None
    rows = income[income.end_date.astype(str).eq('20260930')].copy()
    rows = rows[pd.to_numeric(rows.get('n_income_attr_p'), errors='coerce').notna()]
    dates = []
    for field in ('ann_date', 'f_ann_date'):
        if field in rows:
            dates.extend(x for x in rows[field].dropna().astype(str) if re.fullmatch(r'\d{8}', x))
    return min(dates) if dates else None


def main():
    token = feishu.get_token()
    sheets = feishu.api(
        f'sheets/v3/spreadsheets/{feishu.SPREADSHEET}/sheets/query', token
    )['data']['sheets']
    dated = sorted(
        [(sheet_date(item['title']), item['sheet_id'], item['title']) for item in sheets
         if sheet_date(item['title'])],
        reverse=True,
    )
    snapshots = []
    for date, sheet_id, title in dated:
        values = feishu.read_range(token, f'{sheet_id}!A1:BZ500')
        if not values or '代码' not in values[0] or worker.Q3_NORMAL_HEADER not in values[0]:
            continue
        headers = values[0]
        idx = {header: index for index, header in enumerate(headers)}
        by_code = {}
        for row in values[1:]:
            row = list(row) + [''] * (len(headers) - len(row))
            if row and row[0]:
                by_code[str(row[idx['代码']])] = row[idx[worker.Q3_NORMAL_HEADER]]
        snapshots.append((date, sheet_id, title, by_code))

    archive = {}
    price_dir = worker.RAW / 'prices'
    codes = sorted(path.stem.replace('_SH', '.SH').replace('_SZ', '.SZ').replace('_BJ', '.BJ')
                   for path in price_dir.glob('*.csv'))
    for code in codes:
        announced = announcement_date(code)
        if not announced:
            continue
        for date, sheet_id, title, by_code in snapshots:
            if date >= announced or code not in by_code:
                continue
            cell = by_code[code]
            if '（' in str(cell):
                continue
            baseline = worker.number(cell)
            if baseline is None:
                continue
            archive[code] = {
                'baseline': baseline,
                'source_sheet_id': sheet_id,
                'source_sheet': title,
                'source_date': date,
                'q3_announcement_date': announced,
            }
            break

    OUTPUT.write_text(json.dumps(archive, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'archived': len(archive), 'output': str(OUTPUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
