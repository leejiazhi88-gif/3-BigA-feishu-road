#!/usr/bin/env python3
"""Refresh the copied 2026-10-23 all-stock sheet with 2026-10-23 data."""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts' / 'refresh_all_20261012.py'
spec = importlib.util.spec_from_file_location('refresh_all_worker', SOURCE)
worker = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(worker)

worker.TARGET = 'K3baGL'
worker.TITLE = '2026-10-23（全部）'
worker.ASOF = '20261023'
worker.ASOF_DISPLAY = '2026-10-23'
worker.INDUSTRY_COLOR_MAP = ROOT / 'config' / 'industry_color_map_20261016.json'
worker.PERSONAL_NOTE_STYLE_MAP = ROOT / 'config' / 'personal_note_colors_20261023.json'
worker.WORK = ROOT / 'work' / 'refresh-all-20261023'
worker.RAW = worker.WORK / 'raw'
worker.WORK.mkdir(parents=True, exist_ok=True)
worker.RAW.mkdir(parents=True, exist_ok=True)

if __name__ == '__main__':
    if len(sys.argv) != 2 or sys.argv[1] not in {'prepare', 'apply'}:
        raise SystemExit('Usage: refresh_all_20261023.py prepare|apply')
    worker.prepare() if sys.argv[1] == 'prepare' else worker.apply()
