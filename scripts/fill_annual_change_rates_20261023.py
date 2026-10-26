#!/usr/bin/env python3
"""Fill the three annual forecast change-rate columns on the 2026-10-23 sheet."""
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
OUTPUT = ROOT / 'exports' / 'refresh_20261023' / 'annual_change_rates.json'


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
    before = retry(lambda: feishu.read_range(token, f'{SHEET_ID}!A1:U{row_count}'))
    headers = before[0]
    idx = {header: index for index, header in enumerate(headers)}
    rate_headers = list(worker.ANNUAL_CHANGE_RATE_HEADERS.values())
    assert [worker.column_name(idx[header] + 1) for header in rate_headers] == ['S', 'T', 'U']
    conditions_before = retry(lambda: feishu.condition_formats(token, SHEET_ID))
    filter_before = retry(lambda: feishu.sheet_filter(token, SHEET_ID))

    populated = []
    values = []
    for source_row in before[1:]:
        row = list(source_row) + [''] * (len(headers) - len(source_row))
        if not row or not row[0]:
            continue
        rates = worker.annual_change_rates_from_text(row[idx[worker.ANNUAL_CHANGE_HEADER]])
        rate_values = [rates[year] for year in worker.ANNUAL_CHANGE_RATE_HEADERS]
        values.append(rate_values)
        updated = list(row)
        for header, value in zip(rate_headers, rate_values):
            updated[idx[header]] = value
        populated.append(updated)

    target_range = f'{SHEET_ID}!S2:U{len(values) + 1}'
    retry(lambda: feishu.api(feishu.BASE + '/values', token, 'PUT', {
        'valueRange': {'range': target_range, 'values': values},
    }))
    styles = worker.annual_change_rate_style_payload([headers] + populated)
    retry(lambda: feishu.api(
        feishu.BASE + '/styles_batch_update', token, 'PUT', {'data': styles}))

    after = retry(lambda: feishu.read_range(token, f'{SHEET_ID}!A1:U{row_count}'))
    after_rows = [list(row) + [''] * (len(headers) - len(row)) for row in after[1:]]
    before_rows = [list(row) + [''] * (len(headers) - len(row)) for row in before[1:]]
    for row_number, (old, new) in enumerate(zip(before_rows, after_rows), 2):
        for column in range(len(headers)):
            if column not in {idx[header] for header in rate_headers}:
                assert old[column] == new[column], (row_number, column + 1)
    assert retry(lambda: feishu.condition_formats(token, SHEET_ID)) == conditions_before
    assert retry(lambda: feishu.sheet_filter(token, SHEET_ID)) == filter_before

    counts = {'positive': 0, 'negative': 0, 'zero': 0, 'blank': 0}
    for row in populated:
        for header in rate_headers:
            value = worker.number(row[idx[header]])
            key = ('blank' if value is None else 'positive' if value > 0
                   else 'negative' if value < 0 else 'zero')
            counts[key] += 1
    audit = {
        'sheet_id': SHEET_ID,
        'sheet_name': SHEET_NAME,
        'range': target_range.split('!', 1)[1],
        'rows': len(values),
        **counts,
        'nonempty_values_written': counts['positive'] + counts['negative'] + counts['zero'],
        'other_value_changes': 0,
        'conditional_formats_preserved': True,
        'filter_preserved': True,
    }
    OUTPUT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(audit, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
