"""Remove redundant Tushare source labels from the four composition columns."""
from pathlib import Path
import json
import os
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
WORKDIR = Path(os.environ.get(
    'BUSINESS_COMPOSITION_WORKDIR',
    SCRIPT_DIR.parents[1] / 'work' / 'business-composition-all-20261008',
))
WORKDIR.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SCRIPT_DIR.parent))
sys.path.insert(0, str(SCRIPT_DIR))
import feishu_client as feishu

HEADERS = ['25年收入构成', '25年利润构成', '26年收入构成', '26年利润构成']
REMOVALS = ('来源：2025年报（Tushare）。', '来源：2025年报主营构成。')


def clean(value):
    if not isinstance(value, str):
        return value
    for marker in REMOVALS:
        value = value.replace(marker, '')
    return value


token = feishu.get_token()
target = feishu.TARGET
before = feishu.read_range(token, f'{target}!AX1:BA447')
assert before[0] == HEADERS and len(before) == 447

cf_before = feishu.condition_formats(token)
sheet_filter_before = feishu.sheet_filter(token)
sheet_before = feishu.metadata(token)

updated = [[clean(row[column]) for column in range(2)] for row in before[1:]]
removed = sum(
    str(before[row][column]).count(marker)
    for row in range(1, len(before))
    for column in range(2)
    for marker in REMOVALS
)
assert removed == 885
assert all(not any(marker in str(value) for marker in REMOVALS) for row in updated for value in row)

(WORKDIR / 'before_remove_default_source.json').write_text(
    json.dumps(before, ensure_ascii=False, indent=2, allow_nan=False)
)
feishu.api(feishu.BASE + '/values', token, method='PUT', body={
    'valueRange': {'range': f'{target}!AX2:AY447', 'values': updated}
})

after = feishu.read_range(token, f'{target}!AX1:BA447')
assert after[0] == HEADERS and len(after) == len(before)
for row_number, (old_row, new_row) in enumerate(zip(before[1:], after[1:]), 2):
    assert new_row[:2] == [clean(old_row[0]), clean(old_row[1])], row_number
    assert new_row[2:4] == old_row[2:4], row_number

cf_after = feishu.condition_formats(token)
sheet_filter_after = feishu.sheet_filter(token)
sheet_after = feishu.metadata(token)
assert cf_after == cf_before
assert sheet_filter_after == sheet_filter_before
for key in ('frozen_column_count', 'frozen_row_count', 'column_count', 'row_count'):
    assert sheet_after['grid_properties'][key] == sheet_before['grid_properties'][key]

result = {
    'sheet_id': target,
    'range_updated': f'{target}!AX2:AY447',
    'rows_verified': 446,
    'default_source_labels_removed': removed,
    'forecast_columns_unchanged': True,
    'conditional_formats_preserved': True,
    'filter_preserved': True,
    'frozen_panes_preserved': True,
}
(WORKDIR / 'remove_default_source_verification.json').write_text(
    json.dumps(result, ensure_ascii=False, indent=2)
)
print(json.dumps(result, ensure_ascii=False, indent=2))
