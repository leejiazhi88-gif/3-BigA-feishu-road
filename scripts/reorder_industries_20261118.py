"""Reorder Nov17's existing rows using official SW caps, retaining row styles."""
import json
from pathlib import Path
import pandas as pd
from business_composition import feishu_client as f
from industry_market_order import official_caps, sort_market

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/industry-sort-20261118'
TARGET = 'sCZJ9O'


def main():
    token = f.get_token()
    before = f.read_range(token, f'{TARGET}!A1:BL500')
    h = {v: i for i, v in enumerate(before[0])}
    rows = [r for r in before[1:] if r and r[0]]
    current = [r[h['代码']] for r in rows]
    assert len(current) == len(set(current)) == 480
    members = pd.read_csv(ROOT / 'work/refresh-all-20261117/raw/industry_members.csv')
    members = members.sort_values(['ts_code', 'in_date']).drop_duplicates('ts_code', keep='last')
    selected = pd.DataFrame({'ts_code': current, 'cap_yi': [r[h['市值(亿元)']] for r in rows]})
    selected = selected.merge(members, on='ts_code', validate='one_to_one')
    quotes = pd.read_csv(WORK / 'sw_daily_20261117.csv')
    caps = official_caps(quotes, '20261117')
    ordered = sort_market(selected, caps)
    desired = ordered.ts_code.tolist()
    missing = ordered[ordered.l2_cap_yi.isna()][['l2_code', 'l2_name']].drop_duplicates().to_dict('records')
    (WORK / 'before_values.json').write_text(json.dumps(before, ensure_ascii=False))
    plan = []; simulation = current.copy()
    for i, code in enumerate(desired):
        if simulation[i] == code:
            continue
        j = simulation.index(code, i + 1)
        length = 1
        while j + length < len(simulation) and i + length < len(desired) and simulation[j + length] == desired[i + length]:
            length += 1
        plan.append({'start_index': j + 1, 'end_index': j + length, 'destination_index': i + 1})
        block = simulation[j:j + length]; del simulation[j:j + length]; simulation[i:i] = block
    assert simulation == desired
    print(json.dumps({'moves': len(plan), 'missing_official_l2': missing}, ensure_ascii=False), flush=True)
    cf = f.condition_formats(token, TARGET)
    (WORK / 'before_cf.json').write_text(json.dumps(cf, ensure_ascii=False))
    for n, move in enumerate(plan, 1):
        f.api(f'sheets/v3/spreadsheets/{f.SPREADSHEET}/sheets/{TARGET}/move_dimension', token, 'POST', {
            'source': {'major_dimension': 'ROWS', 'start_index': move['start_index'], 'end_index': move['end_index']},
            'destination_index': move['destination_index'],
        })
        if n == 1:
            check = f.read_range(token, f'{TARGET}!A1:BL500')
            expect = current.copy(); a, b, d = move['start_index']-1, move['end_index'], move['destination_index']-1
            block = expect[a:b]; del expect[a:b]; expect[d:d] = block
            assert [r[h['代码']] for r in check[1:] if r and r[0]] == expect, 'Unexpected move semantics'
        if n % 10 == 0:
            print(f'moved {n}/{len(plan)} blocks', flush=True)
    after = f.read_range(token, f'{TARGET}!A1:BL500')
    assert after[0] == before[0]
    actual = [r for r in after[1:] if r and r[0]]
    assert [r[h['代码']] for r in actual] == desired
    old = {r[h['代码']]: r for r in rows}
    assert all(r == old[r[h['代码']]] for r in actual), 'Row values changed'
    audit = {'sheet_id': TARGET, 'date': '2026-11-17', 'companies': len(actual),
             'order': 'sw_daily L1 desc, L2 desc, daily_basic company cap desc',
             'missing_official_l2_sort_last': missing, 'row_moves': len(plan), 'values_preserved': True}
    (WORK / 'online_audit.json').write_text(json.dumps(audit, ensure_ascii=False, indent=2))
    ordered[['ts_code', 'l1_code', 'l1_name', 'l2_code', 'l2_name', 'l1_cap_yi', 'l2_cap_yi', 'cap_yi']].to_csv(WORK/'order.csv', index=False)
    print(json.dumps(audit, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
