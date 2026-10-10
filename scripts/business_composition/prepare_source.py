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
sys.path.insert(0, str(SCRIPT_DIR.parent))
import refresh_all_20261008 as refresh


def save(name, value):
    (HERE / name).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False))


worker = refresh.load_worker()
token = worker.old.b.get_feishu_token(worker.old.b.DEFAULT_FEISHU_ENV)
values = worker.read_values(token)
values_with_notes = worker.api(
    f'{worker.BASE}/values/{refresh.TARGET}!A1:AW500?valueRenderOption=UnformattedValue', token
)['data']['valueRange']['values']
rows = [row for row in values[1:] if row and row[0]]
assert len(rows) == 446
assert len(values[0]) == 48
assert len({str(row[3]) for row in rows}) == len(rows)

metadata = worker.api(
    f'sheets/v3/spreadsheets/{worker.old.SPREADSHEET}/sheets/query', token
)
sheet = next(x for x in metadata['data']['sheets'] if x['sheet_id'] == refresh.TARGET)
conditions = worker.api(
    f'{worker.BASE}/condition_formats?sheet_ids={refresh.TARGET}', token
)
sheet_filter = worker.api(
    f'sheets/v3/spreadsheets/{worker.old.SPREADSHEET}/sheets/{refresh.TARGET}/filter', token
)

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
