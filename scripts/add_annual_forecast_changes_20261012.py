#!/usr/bin/env python3
"""Insert and populate the per-refresh annual forecast change column."""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work' / 'refresh-all-20261012' / 'annual-change-column'
WORK.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))
import feishu_client as feishu

TARGET = 'avlLqL'
HEADER = '本次刷新年度预测变化'
EXPECTED_Q = '2025净利润同比%(实际/预测)'


def save(name, value):
    (WORK / name).write_text(json.dumps(value, ensure_ascii=False, indent=2))


def fmt_number(value):
    value = float(value)
    return str(int(value)) if value.is_integer() else f'{value:.1f}'


def change_text(change):
    year = re.match(r'(20\d{2})', change['field']).group(1)
    old, ratio = change['old'], change['change_ratio']
    if old in ('', None) or ratio is None:
        return f'{year}年（旧值无，新增预测）'
    return f'{year}年（旧值{fmt_number(old)}，{ratio:+.1%}）'


token = feishu.get_token()
before = feishu.read_range(token, f'{TARGET}!A1:BD500')
column_already_present = before[0][16] == HEADER
assert column_already_present or before[0][16] == EXPECTED_Q, before[0][16]
cf_before = feishu.condition_formats(token)
filter_before = feishu.sheet_filter(token)
meta_before = feishu.metadata(token)
save('before.json', before)
save('conditional_formats_before.json', cf_before)
save('filter_before.json', filter_before)
save('metadata_before.json', meta_before)

changes = json.loads((ROOT / 'exports/refresh_20261009/forecast_changes.json').read_text())
annual_fields = {f'{year}净利润(预测,亿元)' for year in (2026, 2027, 2028)}
by_code = defaultdict(list)
for change in changes:
    if change['field'] in annual_fields:
        by_code[str(change['code'])].append(change)
for code in by_code:
    by_code[code].sort(key=lambda item: item['field'])

if column_already_present:
    inserted = before
else:
    feishu.api(feishu.BASE + '/dimension_range', token, method='POST', body={
        'dimension': {'sheetId': TARGET, 'majorDimension': 'COLUMNS',
                      'startIndex': 16, 'endIndex': 17},
        'inheritStyle': 'BEFORE',
    })
    inserted = feishu.read_range(token, f'{TARGET}!A1:BD500')
    assert inserted[0][16] in ('', None)
    assert inserted[0][:16] == before[0][:16]
    assert inserted[0][17:] == before[0][16:]
code_index = inserted[0].index('代码')
values = [[HEADER]]
changed_rows = 0
annual_changes = 0
for row in inserted[1:]:
    row = list(row) + [''] * (len(inserted[0]) - len(row))
    code = str(row[code_index]) if row and row[0] else ''
    row_changes = by_code.get(code, [])
    values.append(['；'.join(change_text(item) for item in row_changes)])
    if row_changes:
        changed_rows += 1
        annual_changes += len(row_changes)

feishu.api(feishu.BASE + '/values', token, method='PUT', body={
    'valueRange': {'range': f'{TARGET}!Q1:Q{len(values)}', 'values': values},
})
feishu.api(feishu.BASE + '/dimension_range', token, method='PUT', body={
    'dimension': {'sheetId': TARGET, 'majorDimension': 'COLUMNS',
                  'startIndex': 16, 'endIndex': 17},
    'dimensionProperties': {'fixedSize': 260},
})

after = feishu.read_range(token, f'{TARGET}!A1:BD500')
assert after[0][16] == HEADER
for row_number, row in enumerate(after[1:], 2):
    row = list(row) + [''] * (len(after[0]) - len(row))
    code = str(row[code_index]) if row and row[0] else ''
    expected = '；'.join(change_text(item) for item in by_code.get(code, []))
    assert row[16] == expected, (row_number, code, row[16], expected)
    old = list(before[row_number - 1]) + [''] * (len(before[0]) - len(before[row_number - 1]))
    assert row[:16] == old[:16]
    assert row[17:] == (old[17:] if column_already_present else old[16:])

cf_after = feishu.condition_formats(token)
filter_after = feishu.sheet_filter(token)
meta_after = feishu.metadata(token)
assert len(cf_after['data']['sheet_condition_formats']) == len(cf_before['data']['sheet_condition_formats'])
if column_already_present:
    assert cf_after == cf_before
    assert filter_after == filter_before
expected_columns = meta_before['grid_properties']['column_count'] + (0 if column_already_present else 1)
assert meta_after['grid_properties']['column_count'] == expected_columns
for key in ('frozen_column_count', 'frozen_row_count', 'row_count'):
    assert meta_after['grid_properties'][key] == meta_before['grid_properties'][key]

result = {
    'sheet_id': TARGET,
    'column': 'Q',
    'header': HEADER,
    'changed_companies': changed_rows,
    'annual_change_records': annual_changes,
    'used_existing_column': column_already_present,
    'other_values_preserved': True,
    'conditional_format_rule_count_before': len(cf_before['data']['sheet_condition_formats']),
    'conditional_format_rule_count_after': len(cf_after['data']['sheet_condition_formats']),
    'filter_present_after': bool(filter_after),
    'url': 'https://my.feishu.cn/wiki/DlRmwrJOgiWIVhkWZtsc6h0Bnnd?sheet=' + TARGET,
}
save('verification.json', result)
print(json.dumps(result, ensure_ascii=False, indent=2))
