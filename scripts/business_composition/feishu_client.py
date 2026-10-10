from pathlib import Path
import json
import os

import requests

SPREADSHEET = 'UJJesUWvehxTbNtNpV2cHuDcnIc'
TARGET = 'cXtmBx'
BASE = f'sheets/v2/spreadsheets/{SPREADSHEET}'
DEFAULT_ENV = Path(os.environ.get(
    'FEISHU_ENV',
    '/Users/fuguiplus/Documents/Codex/2026-04-30/new-chat/xiaoniuma-feishu/.env',
))


def api(path, token=None, method='GET', body=None):
    headers = {'Authorization': f'Bearer {token}'} if token else {}
    response = requests.request(
        method, 'https://open.feishu.cn/open-apis/' + path,
        headers=headers, json=body, timeout=45,
    )
    response.raise_for_status()
    result = response.json()
    if result.get('code', 0) != 0:
        raise RuntimeError(f"Feishu error {result.get('code')}: {result.get('msg')}")
    return result


def get_token():
    env = {}
    if DEFAULT_ENV.exists():
        for line in DEFAULT_ENV.read_text().splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip().strip('"').strip("'")
    app_id = os.environ.get('FEISHU_APP_ID', env.get('FEISHU_APP_ID'))
    secret = os.environ.get('FEISHU_APP_SECRET', env.get('FEISHU_APP_SECRET'))
    if not app_id or not secret:
        raise RuntimeError('Missing FEISHU_APP_ID / FEISHU_APP_SECRET')
    return api('auth/v3/tenant_access_token/internal', method='POST', body={
        'app_id': app_id, 'app_secret': secret,
    })['tenant_access_token']


def read_range(token, address):
    return api(
        f'{BASE}/values/{address}?valueRenderOption=UnformattedValue', token
    )['data']['valueRange']['values']


def metadata(token):
    data = api(f'sheets/v3/spreadsheets/{SPREADSHEET}/sheets/query', token)
    return next(x for x in data['data']['sheets'] if x['sheet_id'] == TARGET)


def condition_formats(token):
    return api(f'{BASE}/condition_formats?sheet_ids={TARGET}', token)


def sheet_filter(token):
    return api(
        f'sheets/v3/spreadsheets/{SPREADSHEET}/sheets/{TARGET}/filter', token
    )
