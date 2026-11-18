"""Industry order matches project 2.2's same-day sw_daily published cap.

Missing official quotes sort last within their parent, by industry code;
never substitute company-cap sums. Company selection/cap fields are unchanged.
"""
import math


def official_caps(frame, asof):
    assert not frame.empty and len(frame) < 4000, 'Missing/truncated SW quotes'
    assert set(frame.trade_date.astype(str)) == {asof}, 'SW quote date differs'
    assert not frame.ts_code.duplicated().any(), 'Duplicate SW quotes'
    return {r.ts_code: float(r.total_mv) / 10000 for r in frame.itertuples()
            if r.total_mv is not None and math.isfinite(float(r.total_mv))
            and float(r.total_mv) > 0}


def sort_market(selected, caps):
    result = selected.copy()
    result['l1_cap_yi'] = result.l1_code.map(caps)
    result['l2_cap_yi'] = result.l2_code.map(caps)
    assert result.l1_cap_yi.notna().all(), 'Missing official L1 quote'
    return result.sort_values(
        ['l1_cap_yi', 'l1_code', 'l2_cap_yi', 'l2_code', 'cap_yi', 'ts_code'],
        ascending=[False, True, False, True, False, True],
        na_position='last', kind='mergesort')
