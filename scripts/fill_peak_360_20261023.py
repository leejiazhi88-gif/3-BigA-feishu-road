#!/usr/bin/env python3
"""Populate the 360-session peak return column on the 2026-10-23 sheet."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))

import refresh_all_20261012 as worker
from business_composition import feishu_client as feishu

SHEET_ID = 'K3baGL'
AS_OF = '2026-10-23'
HEADER = worker.PEAK_RETURN_HEADER
PRICE_DIR = ROOT / 'work' / 'refresh-all-20261023' / 'raw' / 'prices'
AUDIT_PATH = ROOT / 'exports' / 'refresh_20261023' / 'peak_360_return.json'


def main():
    token = feishu.get_token()
    rows = feishu.read_range(token, f'{SHEET_ID}!A1:BF500')
    headers = rows[0]
    indices = {header: index for index, header in enumerate(headers)}
    assert HEADER in indices, headers
    assert '代码' in indices, headers
    populated = [list(row) + [''] * (len(headers) - len(row))
                 for row in rows[1:] if row and row[0]]

    output = []
    numeric = []
    shorter_history = []
    for row in populated:
        code = str(row[indices['代码']])
        path = PRICE_DIR / f'{worker.code_file(code)}.csv'
        history = pd.read_csv(path, dtype={'trade_date': str})
        available_days = len(history.sort_values('trade_date').drop_duplicates('trade_date', keep='last'))
        value = worker.peak_return_value(history)
        cell = worker.fmt_pct_fraction(value) if value is not None else '历史不足'
        output.append([cell])
        if value is not None:
            numeric.append(cell)
        if available_days < 360:
            shorter_history.append({'code': code, 'available_days': available_days})

    column = worker.column_name(indices[HEADER] + 1)
    end_row = len(output) + 1
    before_column = [[row[indices[HEADER]]] for row in populated]
    feishu.api(feishu.BASE + '/values', token, 'PUT', {
        'valueRange': {'range': f'{SHEET_ID}!{column}2:{column}{end_row}', 'values': output}
    })
    after = feishu.read_range(token, f'{SHEET_ID}!{column}2:{column}{end_row}')
    assert len(after) == len(output), (len(after), len(output))
    for row_number, (expected, actual) in enumerate(zip(output, after), 2):
        actual_value = actual[0] if actual else ''
        expected_value = expected[0]
        if isinstance(expected_value, (int, float)) and isinstance(actual_value, (int, float)):
            assert math.isclose(float(expected_value), float(actual_value), abs_tol=1e-12), row_number
        else:
            assert expected_value == actual_value, (row_number, expected_value, actual_value)

    audit = {
        'sheet_id': SHEET_ID,
        'sheet_name': '2026-10-23（全部）',
        'as_of': AS_OF,
        'column': column,
        'header': HEADER,
        'definition': '当日收盘价 / 最近最多360个交易日内最高收盘价 - 1；不足360日时使用全部可用交易日',
        'window_includes_as_of_date': True,
        'written_range': f'{column}2:{column}{end_row}',
        'company_count': len(output),
        'numeric_count': len(numeric),
        'shorter_than_360_days_count': len(shorter_history),
        'shorter_history': shorter_history,
        'minimum': min(numeric) if numeric else None,
        'maximum': max(numeric) if numeric else None,
        'changed_cells': sum(a != b for a, b in zip(before_column, output)),
        'values_verified': True,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    AUDIT_PATH.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
