#!/usr/bin/env python3
"""Refresh the copied 2026-10-16 all-stock sheet with 2026-10-16 data."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts' / 'refresh_all_20261012.py'
spec = importlib.util.spec_from_file_location('refresh_all_20261012_worker', SOURCE)
worker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(worker)

worker.TARGET = 'tmJVrh'
worker.TITLE = '2026-10-16（全部）'
worker.ASOF = '20261016'
worker.ASOF_DISPLAY = '2026-10-16'
worker.WORK = ROOT / 'work' / 'refresh-all-20261016'
worker.RAW = worker.WORK / 'raw'
worker.WORK.mkdir(parents=True, exist_ok=True)
worker.RAW.mkdir(parents=True, exist_ok=True)


def assert_supported_layout():
    """Stop before writing when users add columns to the copied sheet."""
    token = worker.feishu.get_token()
    metadata = worker.feishu.metadata(token, worker.TARGET)
    columns = metadata['grid_properties']['column_count']
    headers = worker.feishu.read_range(
        token, f'{worker.TARGET}!A1:{worker.column_name(columns)}1')[0]
    worker.validate_headers(headers)

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'prepare', 'apply'}:
        raise SystemExit('Usage: refresh_all_20261016.py prepare|apply')
    assert_supported_layout()
    worker.prepare() if sys.argv[1] == 'prepare' else worker.apply()
