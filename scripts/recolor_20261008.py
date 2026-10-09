import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'dividend-estimates'))
sys.path.insert(0, str(ROOT / 'all-a-share-0915'))
import build as d


SHEET = 'cXtmBx'
BASE = f'sheets/v2/spreadsheets/{d.r.SPREADSHEET}'
spec = importlib.util.spec_from_file_location(
    'color_rules_1010', ROOT / 'all-a-share-0915' / 'build_600_top2.py'
)
rules = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(rules)
rules.SHEET = SHEET

token = d.r.b.get_feishu_token(d.r.b.DEFAULT_FEISHU_ENV)
values = d.api(
    f'{BASE}/values/{SHEET}!A1:AV450?valueRenderOption=UnformattedValue', token=token
)['data']['valueRange']['values']
values = [values[0]] + [row for row in values[1:] if row and row[0]]
condition_before = d.api(BASE + f'/condition_formats?sheet_ids={SHEET}', token=token)
styles = rules.style_payload(values)
d.api(BASE + '/styles_batch_update', token=token, method='PUT', body={'data': styles})
condition_after = d.api(BASE + f'/condition_formats?sheet_ids={SHEET}', token=token)
assert condition_after == condition_before
result = {
    'rows': len(values) - 1,
    'style_batches': len(styles),
    'g10_value': values[9][6],
    'g10_expected_font_color': '#00B050',
    'conditional_format_rules': len(condition_after['data']['sheet_condition_formats']),
    'conditional_formats_unchanged': True,
}
print(json.dumps(result, ensure_ascii=False, indent=2))
