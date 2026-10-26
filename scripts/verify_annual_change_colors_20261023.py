#!/usr/bin/env python3
"""Export the Feishu workbook and verify saved annual-change font colors."""
from __future__ import annotations

import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parents[1]
SPREADSHEET = 'UJJesUWvehxTbNtNpV2cHuDcnIc'
SHEET_NAME = os.environ.get('ANNUAL_CHANGE_SHEET_NAME', '2026-10-23（全部）')
ENV_FILE = Path(os.environ.get(
    'FEISHU_ENV',
    '/Users/fuguiplus/Documents/Codex/2026-04-30/new-chat/xiaoniuma-feishu/.env',
))
OUTPUT = ROOT / os.environ.get(
    'ANNUAL_CHANGE_EXPORT', 'outputs/annual-change-color-fix/2026-10-23-all.xlsx')
AUDIT = ROOT / os.environ.get(
    'ANNUAL_CHANGE_AUDIT', 'exports/refresh_20261023/annual_change_colors.json')


def request_json(path, token=None, method='GET', body=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        'https://open.feishu.cn/open-apis/' + path,
        data=data,
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=45) as response:
        result = json.load(response)
    if result.get('code', 0) != 0:
        raise RuntimeError(f"Feishu error {result.get('code')}: {result.get('msg')}")
    return result


def credentials():
    values = {}
    for line in ENV_FILE.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return (
        os.environ.get('FEISHU_APP_ID', values.get('FEISHU_APP_ID')),
        os.environ.get('FEISHU_APP_SECRET', values.get('FEISHU_APP_SECRET')),
    )


def token():
    app_id, secret = credentials()
    return request_json('auth/v3/tenant_access_token/internal', method='POST', body={
        'app_id': app_id,
        'app_secret': secret,
    })['tenant_access_token']


def export_workbook(access_token):
    task = request_json('drive/v1/export_tasks', access_token, 'POST', {
        'file_extension': 'xlsx',
        'token': SPREADSHEET,
        'type': 'sheet',
    })
    ticket = task['data']['ticket']
    file_token = None
    for _ in range(30):
        query = urllib.parse.urlencode({'token': SPREADSHEET})
        status = request_json(
            f'drive/v1/export_tasks/{ticket}?{query}', access_token)['data']['result']
        if status.get('job_status') == 0 and status.get('file_token'):
            file_token = status['file_token']
            break
        if status.get('job_status') not in (None, 1, 2):
            raise RuntimeError(f'Export failed: {status}')
        time.sleep(1)
    if not file_token:
        raise TimeoutError('Feishu export did not finish')

    request = urllib.request.Request(
        'https://open.feishu.cn/open-apis/'
        f'drive/v1/export_tasks/file/{file_token}/download',
        headers={'Authorization': f'Bearer {access_token}'},
    )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(request, timeout=90) as response:
        OUTPUT.write_bytes(response.read())


def expected_color(text):
    matches = re.findall(
        r'(20\d{2})年（旧值[^，]*，(新增预测|[-+]?\d+(?:\.\d+)?%)）',
        str(text or ''),
    )
    if not matches:
        return '000000'
    _, movement = min(matches, key=lambda item: int(item[0]))
    if movement == '新增预测':
        return '000000'
    ratio = float(movement.rstrip('%'))
    return '00B050' if ratio > 0 else 'C00000' if ratio < 0 else '000000'


def actual_color(cell):
    color = cell.font.color
    if color is None:
        return '000000'
    if color.type != 'rgb':
        return f'{color.type}:{color.indexed or color.theme}'
    return str(color.rgb)[-6:].upper()


def main():
    export_workbook(token())
    workbook = openpyxl.load_workbook(OUTPUT, data_only=False)
    sheet = workbook[SHEET_NAME]
    mismatches = []
    counts = {'00B050': 0, 'C00000': 0, '000000': 0}
    checked = 0
    for row in range(2, sheet.max_row + 1):
        cell = sheet[f'R{row}']
        if not cell.value:
            continue
        expected = expected_color(cell.value)
        actual = actual_color(cell)
        checked += 1
        counts[expected] += 1
        if actual != expected:
            mismatches.append({
                'row': row,
                'value': cell.value,
                'expected': expected,
                'actual': actual,
            })
    audit = json.loads(AUDIT.read_text())
    assert checked == audit['nonempty']
    assert not mismatches, mismatches[:10]
    audit.update({
        'export_file': str(OUTPUT.relative_to(ROOT)),
        'export_checked': checked,
        'style_mismatches': len(mismatches),
        'export_font_colors_verified': True,
    })
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({
        'file': str(OUTPUT),
        'checked': checked,
        'green': counts['00B050'],
        'red': counts['C00000'],
        'black': counts['000000'],
        'style_mismatches': len(mismatches),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
