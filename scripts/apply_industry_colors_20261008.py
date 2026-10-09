import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'dividend-estimates'))
from industry_colors import style_payload
import build as d


SHEET = 'cXtmBx'
BASE = f'sheets/v2/spreadsheets/{d.r.SPREADSHEET}'
MAPPING = ROOT / 'industry_color_map_20260928.json'
token = d.r.b.get_feishu_token(d.r.b.DEFAULT_FEISHU_ENV)
values = d.api(
    f'{BASE}/values/{SHEET}!A1:AV500?valueRenderOption=UnformattedValue', token=token
)['data']['valueRange']['values']
condition_before = d.api(BASE + f'/condition_formats?sheet_ids={SHEET}', token=token)
styles, result = style_payload(values, SHEET, MAPPING)
d.api(BASE + '/styles_batch_update', token=token, method='PUT', body={'data': styles})
condition_after = d.api(BASE + f'/condition_formats?sheet_ids={SHEET}', token=token)
assert condition_after == condition_before
result.update({
    'style_batches': len(styles),
    'conditional_format_rules': len(condition_after['data']['sheet_condition_formats']),
    'conditional_formats_unchanged': True,
})
print(json.dumps(result, ensure_ascii=False, indent=2))
