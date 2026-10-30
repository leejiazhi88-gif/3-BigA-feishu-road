"""Fetch current broker records without moving the sheet's information cutoff."""
import concurrent.futures
import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import tushare as ts

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/forecast-quality-20261030'


def fetch(code):
    path = WORK / 'raw/report_rc' / (code.replace('.', '_') + '.csv')
    meta = path.with_suffix('.json')
    if path.exists() and meta.exists():
        return json.loads(meta.read_text())
    pro = ts.pro_api()
    for attempt in range(3):
        try:
            frame = pro.report_rc(ts_code=code, start_date='20250101', end_date='20261029')
            frame.to_csv(path, index=False)
            result = {'code': code, 'rows': len(frame), 'fetched_at': datetime.now().isoformat(),
                      'endpoint': 'report_rc', 'asof': '20261029', 'status': 'ok'}
            meta.write_text(json.dumps(result))
            return result
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


if __name__ == '__main__':
    values = json.loads((WORK / 'before.json').read_text())
    i = values[0].index('代码')
    codes = [r[i] for r in values[1:] if r and r[0]]
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for result in pool.map(fetch, codes):
            results.append(result)
            if len(results) % 50 == 0 or len(results) == len(codes):
                print(f'broker fetch {len(results)}/{len(codes)}', flush=True)
    (WORK / 'fetch_log.json').write_text(json.dumps(results, ensure_ascii=False, indent=2))
