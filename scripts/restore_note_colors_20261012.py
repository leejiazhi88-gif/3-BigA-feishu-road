#!/usr/bin/env python3
"""Restore personal-note colors by stock code and keep column B independent."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts' / 'business_composition'))
import feishu_client as feishu

TARGET = 'avlLqL'
COLOR_MAP = ROOT / 'config' / 'personal_note_colors_20261008.json'


token = feishu.get_token()
values = feishu.read_range(token, f'{TARGET}!A1:E500')
headers = values[0]
code_index = headers.index('代码')
mapping = json.loads(COLOR_MAP.read_text())['codes']
groups = {}
restored = 0
new = []
for row_number, row in enumerate(values[1:], 2):
    if not row or not row[0]:
        continue
    row = list(row) + [''] * (len(headers) - len(row))
    code = str(row[code_index])
    style = mapping.get(code, {'backColor': '#FFFFFF', 'foreColor': '#000000'})
    if code in mapping:
        restored += 1
    else:
        new.append(code)
    key = json.dumps(style, sort_keys=True)
    groups.setdefault(key, []).append(f'{TARGET}!B{row_number}:B{row_number}')

payload = []
for style_json, ranges in groups.items():
    for start in range(0, len(ranges), 100):
        payload.append({'ranges': ranges[start:start + 100],
                        'style': json.loads(style_json)})
conditions_before = feishu.condition_formats(token)
feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT', {'data': payload})
conditions_after = feishu.condition_formats(token)
assert conditions_after == conditions_before
result = {'sheet_id': TARGET, 'rows': restored + len(new),
          'restored_from_2026_10_08': restored,
          'new_rows_white': len(new), 'new_codes': new,
          'distinct_styles': len(groups),
          'conditional_formats_preserved': True}
print(json.dumps(result, ensure_ascii=False, indent=2))
