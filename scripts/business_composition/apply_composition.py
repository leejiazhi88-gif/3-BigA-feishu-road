from pathlib import Path
import copy
import json
import math
import os
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
HERE = Path(os.environ.get(
    'BUSINESS_COMPOSITION_WORKDIR',
    SCRIPT_DIR.parents[1] / 'work' / 'business-composition-all-20261008',
))
sys.path.insert(0, str(SCRIPT_DIR.parent))
import refresh_all_20261008 as refresh

TARGET = refresh.TARGET
HEADERS = ['25年收入构成', '25年利润构成', '26年收入构成', '26年利润构成']
MAPPING = json.loads((SCRIPT_DIR.parents[1] / 'config' / 'industry_color_map_20260928.json').read_text())


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


def equivalent(a, b):
    if a in ('', None) and b in ('', None):
        return True
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-10)
    return a == b


def read_range(worker, token, address):
    return worker.api(
        f'{worker.BASE}/values/{address}?valueRenderOption=UnformattedValue', token
    )['data']['valueRange']['values']


def current_metadata(worker, token):
    data = worker.api(
        f'sheets/v3/spreadsheets/{worker.old.SPREADSHEET}/sheets/query', token
    )
    return next(x for x in data['data']['sheets'] if x['sheet_id'] == TARGET)


worker = refresh.load_worker()
token = worker.old.b.get_feishu_token(worker.old.b.DEFAULT_FEISHU_ENV)
before = json.loads((HERE / 'before.json').read_text())['values']
before_with_notes = json.loads((HERE / 'before_with_notes.json').read_text())['values']
prepared = json.loads((HERE / 'prepared.json').read_text())
selected_path = HERE / 'selected_prepared.json'
if not selected_path.exists():
    selected_path = SCRIPT_DIR.parents[1] / 'config' / 'selected_business_composition_20261008.json'
selected = {x['code']: x for x in json.loads(selected_path.read_text())}
cf_before = json.loads((HERE / 'cf_before.json').read_text())
filter_before = json.loads((HERE / 'filter_before.json').read_text())
meta_before = json.loads((HERE / 'metadata_before.json').read_text())

assert worker.read_values(token) == before, 'A:AV changed after preparation'
assert read_range(worker, token, f'{TARGET}!A1:AW500') == before_with_notes, 'A:AW changed after preparation'
assert len(prepared) == 446 and [x['row'] for x in prepared] == list(range(2, 448))
assert all(len(x['values']) == 4 and all(x['values']) for x in prepared)
for item in prepared:
    row = before[item['row'] - 1]
    assert row[0] == item['name'] and row[3] == item['code']
    if item['code'] in selected:
        assert item['values'] == selected[item['code']]['values']

existing = read_range(worker, token, f'{TARGET}!AX1:BA447')
existing_headers = list(existing[0]) + [''] * (4-len(existing[0]))
assert existing and existing_headers in (HEADERS, HEADERS[:3] + [''])
assert all(all(v in ('', None) for v in row) for row in existing[1:])

payload_values = [HEADERS] + [x['values'] for x in prepared]
worker.api(worker.BASE + '/values', token, method='PUT', body={
    'valueRange': {'range': f'{TARGET}!AX1:BA447', 'values': payload_values}
})

styles = [
    {'ranges': [f'{TARGET}!AX2:BA447'], 'style': {'wordWrap': True}},
    {'ranges': [f'{TARGET}!AX1:AY1'], 'style': {
        'font': {'bold': True}, 'backColor': '#E8F0FE', 'wordWrap': True}},
    {'ranges': [f'{TARGET}!AZ1:BA1'], 'style': {
        'font': {'bold': True}, 'backColor': '#FFF2CC', 'wordWrap': True}},
]
by_color = {}
for row_number, row in enumerate(before[1:447], 2):
    key = f'{str(row[1]).strip()}\t{str(row[2]).strip()}'
    entry = MAPPING['industry_pairs'].get(key)
    assert entry is not None, key
    assert entry['b_color'] == entry['c_color']
    by_color.setdefault(entry['b_color'], []).append(f'{TARGET}!AX{row_number}:BA{row_number}')
for color, ranges in by_color.items():
    for start in range(0, len(ranges), 100):
        styles.append({'ranges': ranges[start:start + 100], 'style': {
            'backColor': color, 'wordWrap': True}})
worker.api(worker.BASE + '/styles_batch_update', token, method='PUT', body={'data': styles})
worker.api(worker.BASE + '/dimension_range', token, method='PUT', body={
    'dimension': {'sheetId': TARGET, 'majorDimension': 'COLUMNS',
                  'startIndex': 49, 'endIndex': 53},
    'dimensionProperties': {'fixedSize': 460},
})

after_old = worker.read_values(token)
assert after_old == before, 'Existing A:AV cells changed'
assert read_range(worker, token, f'{TARGET}!A1:AW500') == before_with_notes, 'Existing A:AW cells changed'
after_new = read_range(worker, token, f'{TARGET}!AX1:BA447')
assert len(after_new) == 447
for row_number, (expected, actual) in enumerate(zip(payload_values, after_new), 1):
    actual = list(actual) + [''] * (4 - len(actual))
    for column, (a, b) in enumerate(zip(expected, actual), 49):
        assert equivalent(a, b), f'mismatch row={row_number} column={column}'

cf_after = worker.api(f'{worker.BASE}/condition_formats?sheet_ids={TARGET}', token)
filter_after = worker.api(
    f'sheets/v3/spreadsheets/{worker.old.SPREADSHEET}/sheets/{TARGET}/filter', token
)
meta_after = current_metadata(worker, token)
assert cf_after == cf_before
assert filter_after == filter_before
for key in ('frozen_column_count', 'frozen_row_count', 'row_count'):
    assert meta_after['grid_properties'][key] == meta_before['grid_properties'][key]

unavailable = {
    '25_revenue': sum('未取得可核验' in x['values'][0] for x in prepared),
    '25_profit': sum('未取得可核验' in x['values'][1] for x in prepared),
    '26_revenue': sum('缺少可核验' in x['values'][2] for x in prepared),
    '26_profit': sum('缺少可核验' in x['values'][3] for x in prepared),
}
result = {
    'sheet_id': TARGET,
    'url': 'https://my.feishu.cn/wiki/DlRmwrJOgiWIVhkWZtsc6h0Bnnd?sheet=' + TARGET,
    'range': f'{TARGET}!AX1:BA447',
    'stocks': len(prepared),
    'cells_verified': len(prepared) * 4 + 4,
    'selected_rows_reused_exactly': sum(x['code'] in selected for x in prepared),
    'previous_columns_preserved': True,
    'conditional_format_rules': len(cf_after['data']['sheet_condition_formats']),
    'conditional_formats_preserved': True,
    'filter_preserved': True,
    'frozen_rows': meta_after['grid_properties']['frozen_row_count'],
    'frozen_columns': meta_after['grid_properties']['frozen_column_count'],
    'industry_background_extended_to': 'BA',
    'unavailable': unavailable,
}
save('after.json', {'values': before + []})
save('verification.json', result)
print(json.dumps(result, ensure_ascii=False, indent=2))
