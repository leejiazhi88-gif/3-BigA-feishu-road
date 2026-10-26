#!/usr/bin/env python3
"""Reapply annual forecast change colors from the visible cell text."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import refresh_all_20261012 as worker
from business_composition import feishu_client as feishu

SHEET_ID = 'K3baGL'
SHEET_NAME = '2026-10-23（全部）'
OUTPUT = ROOT / 'exports' / 'refresh_20261023' / 'annual_change_colors.json'


def retry(call):
    for attempt in range(3):
        try:
            return call()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main():
    worker.TARGET = SHEET_ID
    token = feishu.get_token()
    metadata = retry(lambda: feishu.metadata(token, SHEET_ID))
    row_count = metadata['grid_properties']['row_count']
    before = retry(lambda: feishu.read_range(token, f'{SHEET_ID}!A1:R{row_count}'))
    headers = before[0]
    idx = {header: index for index, header in enumerate(headers)}
    annual_index = idx[worker.ANNUAL_CHANGE_HEADER]
    annual_column = worker.column_name(annual_index + 1)
    assert annual_column == 'R', annual_column

    conditions_before = retry(lambda: feishu.condition_formats(token, SHEET_ID))
    filter_before = retry(lambda: feishu.sheet_filter(token, SHEET_ID))
    groups = {'#00B050': [], '#C00000': [], '#000000': []}
    rows = []
    for row_number, source_row in enumerate(before[1:], 2):
        row = list(source_row) + [''] * (len(headers) - len(source_row))
        text = row[annual_index]
        if not text:
            continue
        color = worker.annual_change_color_from_text(text)
        address = f'{SHEET_ID}!{annual_column}{row_number}:{annual_column}{row_number}'
        groups[color].append(address)
        rows.append({
            'row': row_number,
            'code': row[idx['代码']],
            'name': row[idx['名称']],
            'text': text,
            'color': color,
        })

    styles = []
    for color, ranges in groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({
                'ranges': ranges[start:start + 100],
                'style': {'foreColor': color},
            })
    retry(lambda: feishu.api(
        feishu.BASE + '/styles_batch_update', token, 'PUT', {'data': styles}))

    after = retry(lambda: feishu.read_range(token, f'{SHEET_ID}!A1:R{row_count}'))
    conditions_after = retry(lambda: feishu.condition_formats(token, SHEET_ID))
    filter_after = retry(lambda: feishu.sheet_filter(token, SHEET_ID))
    assert after == before, 'Cell values changed while applying font colors'
    assert conditions_after == conditions_before, 'Conditional formatting changed'
    assert filter_after == filter_before, 'Sheet filter changed'

    audit = {
        'sheet_id': SHEET_ID,
        'sheet_name': SHEET_NAME,
        'column': annual_column,
        'nonempty': len(rows),
        'green': len(groups['#00B050']),
        'red': len(groups['#C00000']),
        'black': len(groups['#000000']),
        'value_changes': 0,
        'conditional_formats_preserved': True,
        'filter_preserved': True,
        'rows': rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in audit.items() if key != 'rows'},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
