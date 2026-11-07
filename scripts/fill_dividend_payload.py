#!/usr/bin/env python3
"""Fill BB:BD in a prepared 2026 all-stock payload using Tushare evidence.

This never writes to Feishu. Feed its output to finalize_copied_sheet.py.
Requires TUSHARE_TOKEN and the project's tushare/pandas dependencies.
"""
import argparse
import copy
import json
import math
import os
import time
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


DIVIDEND_FIELDS = ('ts_code,end_date,ann_date,div_proc,cash_div_tax,ex_date,'
                   'base_share,update_flag')
DAILY_FIELDS = 'ts_code,trade_date,total_mv'
STATUS_RANK = {'实施': 4, '股东大会通过': 3, '预案': 2, '预披露': 1}


def number(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError):
        return None


def records(frame):
    return frame.where(frame.notna(), None).to_dict('records')


def query(pro, name, **params):
    time.sleep(.35)
    return records(getattr(pro, name)(**params))


def payout_records(all_records, fiscal_year, asof):
    chosen = {}
    for item in all_records:
        if (str(item.get('end_date') or '').startswith(str(fiscal_year))
                and item.get('div_proc') == '实施'
                and item.get('ex_date')
                and str(item['ex_date']) <= asof
                and number(item.get('cash_div_tax'))
                and number(item.get('base_share'))):
            key = (item['end_date'], item['ex_date'])
            old = chosen.get(key)
            if (old is None or (item.get('update_flag') == '0'
                               and old.get('update_flag') != '0')
                    or (item.get('update_flag') == old.get('update_flag')
                        and str(item.get('ann_date')) > str(old.get('ann_date')))):
                chosen[key] = item
    return list(chosen.values())


def announced_amount(all_records, fiscal_year, asof):
    chosen = {}
    for item in all_records:
        if (str(item.get('end_date') or '').startswith(str(fiscal_year))
                and item.get('ann_date')
                and str(item['ann_date']) <= asof
                and number(item.get('cash_div_tax'))
                and number(item.get('base_share'))):
            key = item['end_date']
            old = chosen.get(key)
            rank = STATUS_RANK.get(item.get('div_proc'), 0)
            old_rank = STATUS_RANK.get(old.get('div_proc'), 0) if old else -1
            if old is None or rank > old_rank or (rank == old_rank and
                    str(item.get('ann_date')) > str(old.get('ann_date'))):
                chosen[key] = item
    return sum(number(x['cash_div_tax']) * number(x['base_share'])
               for x in chosen.values())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--asof', required=True, help='YYYY-MM-DD closing date')
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve():
        parser.error('Use a different output path so the prepared input stays intact')
    if not os.environ.get('TUSHARE_TOKEN'):
        parser.error('TUSHARE_TOKEN is required')
    import tushare as ts
    asof_date = date.fromisoformat(args.asof)
    if asof_date.year != 2026:
        parser.error('This payload has 2025 actual and 2026 forecast columns')
    asof = asof_date.strftime('%Y%m%d')
    prior = asof_date.year - 1
    payload = json.loads(args.input.read_text(encoding='utf-8'))
    result = copy.deepcopy(payload)
    values = result['valueRange']['values']
    headers = values[0]
    idx = {h: i for i, h in enumerate(headers)}
    needed = ('代码', '最新交易日', '市值(亿元)',
              '2025净利润(实际/预测,亿元)', '2026净利润(预测,亿元)',
              '股息率%', '上财年全年股息率（25年·年日均市值）',
              '本财年预估全年股息率（26年）', '2026年股息率估算备注')
    assert all(h in idx for h in needed)
    pro = ts.pro_api(os.environ['TUSHARE_TOKEN'])
    audit = []
    counts = defaultdict(int)
    for rowno, row in enumerate(values[1:], 2):
        if not row or not row[idx['代码']]:
            continue
        row += [''] * (len(headers) - len(row))
        assert str(row[idx['最新交易日']]) == args.asof
        bb, bc, bd, be = (idx[h] for h in needed[-4:])
        if all(row[c] not in ('', None, '待核验') for c in (bb, bc, bd)):
            continue
        code = str(row[idx['代码']])
        old = [row[c] for c in (bb, bc, bd, be)]
        divs = query(pro, 'dividend', ts_code=code, fields=DIVIDEND_FIELDS)
        paid = payout_records(divs, prior, asof)
        payout = sum(number(x['cash_div_tax']) * number(x['base_share']) for x in paid)
        notes = []
        if row[bb] in ('', None):
            cutoff = (asof_date - timedelta(days=365)).strftime('%Y%m%d')
            recent = [x for x in divs if x.get('div_proc') == '实施'
                      and x.get('ex_date') and cutoff <= str(x['ex_date']) <= asof
                      and number(x.get('cash_div_tax'))]
            assert not recent, f'{code} has recent paid dividends but BB is blank'
            row[bb] = 0
            notes.append('近12个月无已实施现金派息，BB=0')
            counts['bb_zero'] += 1
        avg_mv = None
        days = 0
        if row[bc] in ('', None, '待核验') or row[bd] in ('', None, '待核验'):
            daily = query(pro, 'daily_basic', ts_code=code,
                          start_date=f'{prior}0101', end_date=f'{prior}1231',
                          fields=DAILY_FIELDS)
            market_values = [number(x.get('total_mv')) for x in daily]
            market_values = [x for x in market_values if x and x > 0]
            days = len(market_values)
            avg_mv = sum(market_values) / days if days else None
        if row[bc] in ('', None, '待核验'):
            if avg_mv:
                row[bc] = payout / avg_mv if payout else 0
                notes.append(f'BC按{prior}财年已实施税前分红÷{prior}年{days}个交易日日均总市值计算')
                if number(row[bc]) > .10:
                    notes.append('BC超过10%，可能受重组或异常派息影响，需核验可比性')
                counts['bc_numeric'] += 1
            else:
                row[bc] = f'不适用：{prior}年未上市'
                notes.append(f'{prior}年无上市交易日，BC不适用')
                counts['bc_na'] += 1
        if row[bd] in ('', None, '待核验'):
            p25 = number(row[idx['2025净利润(实际/预测,亿元)']])
            p26 = number(row[idx['2026净利润(预测,亿元)']])
            cap = number(row[idx['市值(亿元)']])
            ratio = payout / (p25 * 10000) if p25 and p25 > 0 else None
            if payout and avg_mv and ratio and ratio <= 1 and p26 and p26 > 0 and cap and cap > 0:
                row[bd] = ratio * p26 / cap
                notes.append(f'BD按{prior}派息率×2026预测净利润÷收盘市值估算；非公司承诺')
                counts['bd_model'] += 1
            elif not payout and cap and cap > 0:
                minimum = announced_amount(divs, 2026, asof)
                if minimum > 0:
                    row[bd] = minimum / (cap * 10000)
                    notes.append('BD仅按已公告2026财年现金分红计算下限，全年可能更高')
                    counts['bd_floor'] += 1
                else:
                    row[bd] = '待估：无可比派息基准'
                    notes.append('BD暂无可靠估算依据')
                    counts['bd_status'] += 1
            else:
                row[bd] = ('待估：上市前分红不可直接外推' if not avg_mv else
                           '待估：2026利润预测非正' if not p26 or p26 <= 0 else
                           '待估：2025派息超过当年利润')
                notes.append('BD未机械外推不可比的历史派息率')
                counts['bd_status'] += 1
        if notes:
            previous = str(old[3] or '').strip()
            keep = previous and not any(x in previous for x in (
                '分红金额或基准股本缺失', '缺2025年度分红记录', '缺2026利润预测'))
            row[be] = '；'.join(notes) + ('；原备注：' + previous if keep else '')
        audit.append({'row': rowno, 'code': code, 'old': old,
                      'new': [row[c] for c in (bb, bc, bd, be)],
                      'payout_2025_wan': payout, 'average_2025_mv_wan': avg_mv,
                      'trading_days_2025': days,
                      'dividend_periods': [x['end_date'] for x in paid]})
    blanks = [(n, row[idx['代码']], h) for n, row in enumerate(values[1:], 2)
              if row and row[idx['代码']] for h in needed[-4:-1]
              if row[idx[h]] in ('', None)]
    assert not blanks, blanks[:20]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    args.output.with_suffix('.audit.json').write_text(
        json.dumps({'asof': args.asof, 'source': 'Tushare dividend and daily_basic',
                    'counts': counts, 'changes': audit}, ensure_ascii=False, indent=2) + '\n',
        encoding='utf-8')
    print(json.dumps({'rows_checked': len(audit), 'counts': counts}, ensure_ascii=False))


if __name__ == '__main__':
    main()

