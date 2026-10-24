#!/usr/bin/env python3
"""Apply the recovered locked and rolling Q3 comparisons to the 10-23 sheet."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))

import refresh_all_20261012 as worker
from business_composition import feishu_client as feishu

WORK = ROOT / 'work' / 'refresh-all-20261023'
OUTPUT = ROOT / 'exports' / 'refresh_20261023' / 'q3_dual_comparison.json'


def retry(call):
    for attempt in range(3):
        try:
            return call()
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main():
    before = json.loads((WORK / 'before.json').read_text())
    payload = json.loads((WORK / 'payload.json').read_text())['valueRange']['values']
    headers = payload[0]
    idx = {header: index for index, header in enumerate(headers)}
    locked_header = worker.q3_lock_header(idx)
    locked_index = idx[locked_header]
    normal_index = idx[worker.Q3_NORMAL_HEADER]
    assert normal_index == locked_index + 1
    populated = [row for row in payload[1:] if row and row[0]]
    target_values = [[row[locked_index], row[normal_index]] for row in populated]
    locked_column = worker.column_name(locked_index + 1)
    normal_column = worker.column_name(normal_index + 1)
    target_range = f'{worker.TARGET}!{locked_column}2:{normal_column}{len(populated) + 1}'

    old_rows = [list(row) + [''] * (len(headers) - len(row))
                for row in before[1:] if row and row[0]]
    changes = []
    for row_number, (old, new) in enumerate(zip(old_rows, populated), 2):
        if old[locked_index] != new[locked_index] or old[normal_index] != new[normal_index]:
            changes.append({
                'row': row_number,
                'code': new[idx['代码']],
                'name': new[idx['名称']],
                'locked_old': old[locked_index],
                'locked_new': new[locked_index],
                'rolling_old': old[normal_index],
                'rolling_new': new[normal_index],
            })
    reported_count = sum('未锁定预测' in str(row[normal_index]) for row in populated)
    assert reported_count == 55, reported_count
    comparisons = [
        {
            'row': row_number,
            'code': row[idx['代码']],
            'name': row[idx['名称']],
            'locked_comparison': row[locked_index],
            'rolling_comparison': row[normal_index],
        }
        for row_number, row in enumerate(populated, 2)
        if '未锁定预测' in str(row[normal_index])
    ]

    token = feishu.get_token()
    current = retry(lambda: feishu.read_range(token, worker.sheet_range(before[0])))
    assert current == before, 'Sheet changed after Q3 comparison preparation'
    conditions_before = retry(lambda: feishu.condition_formats(token, worker.TARGET))
    filter_before = retry(lambda: feishu.sheet_filter(token, worker.TARGET))
    retry(lambda: feishu.api(feishu.BASE + '/values', token, 'PUT', {
        'valueRange': {'range': target_range, 'values': target_values},
    }))

    visible = [headers] + populated
    prefixes = (f'{worker.TARGET}!{locked_column}', f'{worker.TARGET}!{normal_column}')
    styles = []
    for entry in worker.font_style_payload(visible):
        ranges = [address for address in entry['ranges'] if address.startswith(prefixes)]
        if ranges:
            styles.append({'ranges': ranges, 'style': entry['style']})
    retry(lambda: feishu.api(
        feishu.BASE + '/styles_batch_update', token, 'PUT', {'data': styles}))

    after = retry(lambda: feishu.read_range(token, target_range))
    assert after == target_values
    assert retry(lambda: feishu.condition_formats(token, worker.TARGET)) == conditions_before
    assert retry(lambda: feishu.sheet_filter(token, worker.TARGET)) == filter_before
    audit = {
        'sheet_id': worker.TARGET,
        'sheet_name': worker.TITLE,
        'range': target_range.split('!', 1)[1],
        'reported_q3_companies': reported_count,
        'changed_companies_this_run': len(changes),
        'locked_comparison_column': locked_column,
        'rolling_comparison_column': normal_column,
        'values_verified': True,
        'conditional_formats_preserved': True,
        'filter_preserved': True,
        'comparisons': comparisons,
        'changes': changes,
    }
    OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: value for key, value in audit.items()
                      if key not in {'changes', 'comparisons'}},
                     ensure_ascii=False, indent=2))


if __name__ == '__main__':
    worker.TARGET = 'K3baGL'
    worker.TITLE = '2026-10-23（全部）'
    main()
