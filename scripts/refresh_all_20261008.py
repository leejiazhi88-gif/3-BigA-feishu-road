from __future__ import annotations

import collections
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from industry_colors import style_payload as industry_style_payload


ROOT = Path(__file__).resolve().parent
TARGET = 'cXtmBx'
TITLE = '2026-10-8（全部）'
ASOF = '20261008'
ASOF_DISPLAY = '2026-10-08'
OUT_ROOT = ROOT / 'refresh-all-20261008'
INDUSTRY_COLORS = ROOT / 'industry_color_map_20260928.json'


def load_worker():
    path = ROOT / 'refresh_all_20260923.py'
    spec = importlib.util.spec_from_file_location('refresh_worker_1010', path)
    worker = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(worker)
    worker.SHEET = TARGET
    worker.ASOF = ASOF
    worker.ASOF_DISPLAY = ASOF_DISPLAY
    worker.ROOT = OUT_ROOT
    worker.RAW = OUT_ROOT / 'raw'
    worker.OUT = OUT_ROOT / 'prepared'
    worker.RAW.mkdir(parents=True, exist_ok=True)
    worker.OUT.mkdir(parents=True, exist_ok=True)
    worker.old.ASOF = ASOF
    worker.old.ASOF_DISPLAY = ASOF_DISPLAY
    worker.old.RAW = worker.RAW
    worker.old.OUT = worker.OUT
    worker.old.b.RAW_DIR = worker.RAW
    worker.old.repair.RAW_DIR = worker.RAW
    return worker


def apply_values_only(worker):
    token = worker.old.b.get_feishu_token(worker.old.b.DEFAULT_FEISHU_ENV)
    before = json.loads((worker.OUT / 'before.json').read_text())
    assert worker.read_values(token) == before, 'Target sheet changed after preparation'
    condition_before = worker.api(
        f'{worker.BASE}/condition_formats?sheet_ids={TARGET}', token
    )
    metadata_before = worker.api(
        f'sheets/v3/spreadsheets/{worker.old.SPREADSHEET}/sheets/query', token
    )
    sheet_before = next(x for x in metadata_before['data']['sheets'] if x['sheet_id'] == TARGET)

    payload = json.loads((worker.OUT / 'payload.json').read_text())
    audit = json.loads((worker.OUT / 'audit.json').read_text())
    worker.api(f'{worker.BASE}/values', token, method='PUT', body=payload)

    # These colors depend on the refreshed values and must be recalculated
    # after every update. Data bars and other conditional formats stay intact.
    visible_values = payload['valueRange']['values'][:len(audit) + 1]
    worker.previous.SHEET = TARGET
    worker.api(
        f'{worker.BASE}/styles_batch_update', token, method='PUT',
        body={'data': worker.previous.style_payload(visible_values)},
    )
    industry_styles, industry_result = industry_style_payload(
        visible_values, TARGET, INDUSTRY_COLORS
    )
    worker.api(
        f'{worker.BASE}/styles_batch_update', token, method='PUT',
        body={'data': industry_styles},
    )

    after = worker.read_values(token)
    rows = [worker.padded(row) for row in after[1:] if row and row[0]]
    condition_after = worker.api(
        f'{worker.BASE}/condition_formats?sheet_ids={TARGET}', token
    )
    metadata_after = worker.api(
        f'sheets/v3/spreadsheets/{worker.old.SPREADSHEET}/sheets/query', token
    )
    sheet_after = next(x for x in metadata_after['data']['sheets'] if x['sheet_id'] == TARGET)

    assert len(rows) == len(audit)
    assert len({str(row[3]) for row in rows}) == len(rows)
    assert collections.Counter(str(row[18]) for row in rows) == {ASOF_DISPLAY: len(rows)}
    assert condition_after == condition_before, 'Conditional formatting changed'
    for key in ('frozen_column_count', 'frozen_row_count', 'column_count', 'row_count'):
        assert sheet_after['grid_properties'][key] == sheet_before['grid_properties'][key]
    counts = collections.Counter(str(row[2]) for row in rows)
    assert min(counts.values()) >= 2

    result = {
        'sheet_id': TARGET,
        'title': TITLE,
        'asof': ASOF_DISPLAY,
        'rows': len(rows),
        'unique_codes': len(rows),
        'over_600': sum(float(row[5]) > 600 for row in rows),
        'l2_categories': len(counts),
        'minimum_per_l2': min(counts.values()),
        'conditional_format_rules': len(condition_after['data']['sheet_condition_formats']),
        'conditional_formats_unchanged': True,
        'frozen_rows': sheet_after['grid_properties']['frozen_row_count'],
        'frozen_columns': sheet_after['grid_properties']['frozen_column_count'],
        'values_verified': True,
        'industry_colors': industry_result,
    }
    (worker.OUT / 'verification.json').write_text(
        json.dumps(result, ensure_ascii=False, indent=2)
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    import sys

    worker = load_worker()
    if len(sys.argv) > 1 and sys.argv[1] == 'apply':
        apply_values_only(worker)
    else:
        worker.prepare()
