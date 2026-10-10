from pathlib import Path
import json
import os
import sys

SCRIPT_DIR = Path(__file__).resolve().parent
HERE = Path(os.environ.get(
    'BUSINESS_COMPOSITION_WORKDIR',
    SCRIPT_DIR.parents[1] / 'work' / 'business-composition-all-20261008',
))
HERE.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(SCRIPT_DIR))
import feishu_client as feishu


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


token = feishu.get_token()
values = feishu.read_range(token, f'{feishu.TARGET}!A1:AV500')
values_with_notes = feishu.read_range(token, f'{feishu.TARGET}!A1:AW500')
rows = [row for row in values[1:] if row and row[0]]
assert len(rows) == 446
assert len(values[0]) == 48
assert len({str(row[3]) for row in rows}) == len(rows)

sheet = feishu.metadata(token)
conditions = feishu.condition_formats(token)
sheet_filter = feishu.sheet_filter(token)

save('before.json', {'values': values})
save('before_with_notes.json', {'values': values_with_notes})
save('metadata_before.json', sheet)
save('cf_before.json', conditions)
save('filter_before.json', sheet_filter)
print(json.dumps({
    'rows': len(rows),
    'columns': len(values[0]),
    'column_count': sheet['grid_properties']['column_count'],
    'condition_formats': len(conditions['data']['sheet_condition_formats']),
    'frozen_rows': sheet['grid_properties']['frozen_row_count'],
    'frozen_columns': sheet['grid_properties']['frozen_column_count'],
}, ensure_ascii=False, indent=2))
