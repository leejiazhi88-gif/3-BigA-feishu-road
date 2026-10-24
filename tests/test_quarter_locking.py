import copy
import unittest
from unittest import mock

import pandas as pd

from scripts import refresh_all_20261012 as refresh


class QuarterLockingTest(unittest.TestCase):
    def setUp(self):
        self.headers = list(refresh.EXPECTED_HEADERS)
        self.idx = {header: index for index, header in enumerate(self.headers)}
        self.row = [''] * len(self.headers)
        self.row[self.idx[refresh.Q3_LOCK_HEADER]] = 10
        self.row[self.idx[refresh.Q3_NORMAL_HEADER]] = 12
        self.row[self.idx[refresh.Q4_NORMAL_HEADER]] = 22
        self.annual = {2025: 80, 2026: 100, 2027: 110, 2028: 120}
        self.weights = {1: .25, 2: .25, 3: .25, 4: .25}

    @staticmethod
    def income(include_q4=False):
        rows = [
            {'end_date': '20260331', 'ann_date': '20260420', 'report_type': '1',
             'f_ann_date': '20260420', 'n_income_attr_p': 100_000_000},
            {'end_date': '20260630', 'ann_date': '20260820', 'report_type': '1',
             'f_ann_date': '20260820', 'n_income_attr_p': 300_000_000},
            {'end_date': '20260930', 'ann_date': '20261020', 'report_type': '1',
             'f_ann_date': '20261020', 'n_income_attr_p': 800_000_000},
        ]
        if include_q4:
            rows.append({'end_date': '20261231', 'ann_date': '20270320',
                         'f_ann_date': '20270320', 'report_type': '1',
                         'n_income_attr_p': 2_000_000_000})
        return pd.DataFrame(rows)

    def test_q3_keeps_locked_and_rolling_baselines_across_refreshes(self):
        with mock.patch.object(refresh.quarter, 'quarter_weights', return_value=self.weights):
            first = refresh.quarterly_values(
                self.row, self.idx, self.income(), self.annual)
            self.assertEqual(first[refresh.Q3_LOCK_HEADER], '5.0（锁定预测10.0）')
            self.assertEqual(first[refresh.Q3_NORMAL_HEADER], '5.0（未锁定预测12.0）')

            repeated_row = copy.deepcopy(self.row)
            repeated_row[self.idx[refresh.Q3_LOCK_HEADER]] = first[refresh.Q3_LOCK_HEADER]
            repeated_row[self.idx[refresh.Q3_NORMAL_HEADER]] = first[refresh.Q3_NORMAL_HEADER]
            repeated = refresh.quarterly_values(
                repeated_row, self.idx, self.income(), self.annual)
            self.assertEqual(repeated[refresh.Q3_LOCK_HEADER], first[refresh.Q3_LOCK_HEADER])
            self.assertEqual(repeated[refresh.Q3_NORMAL_HEADER], first[refresh.Q3_NORMAL_HEADER])

    def test_q4_uses_separate_locked_and_rolling_baselines(self):
        headers = list(self.headers)
        q4_index = headers.index(refresh.Q4_NORMAL_HEADER)
        headers.insert(q4_index, refresh.Q4_LOCK_HEADER)
        idx = {header: index for index, header in enumerate(headers)}
        row = [''] * len(headers)
        row[idx[refresh.Q3_LOCK_HEADER]] = '5.0（锁定预测10.0）'
        row[idx[refresh.Q3_NORMAL_HEADER]] = '5.0（未锁定预测12.0）'
        row[idx[refresh.Q4_LOCK_HEADER]] = 20
        row[idx[refresh.Q4_NORMAL_HEADER]] = 22

        with mock.patch.object(refresh.quarter, 'quarter_weights', return_value=self.weights):
            result = refresh.quarterly_values(row, idx, self.income(True), self.annual)
        self.assertEqual(result[refresh.Q4_LOCK_HEADER], '12.0（锁定预测20.0）')
        self.assertEqual(result[refresh.Q4_NORMAL_HEADER], '12.0（未锁定预测22.0）')

    def test_missing_q3_lock_is_explicit_and_stable(self):
        self.row[self.idx[refresh.Q3_LOCK_HEADER]] = ''
        with mock.patch.object(refresh.quarter, 'quarter_weights', return_value=self.weights):
            first = refresh.quarterly_values(
                self.row, self.idx, self.income(), self.annual, 'NO_ARCHIVE')
            self.assertEqual(first[refresh.Q3_LOCK_HEADER], '5.0（锁定预测无）')
            repeated_row = copy.deepcopy(self.row)
            repeated_row[self.idx[refresh.Q3_LOCK_HEADER]] = first[refresh.Q3_LOCK_HEADER]
            repeated = refresh.quarterly_values(
                repeated_row, self.idx, self.income(), self.annual, 'NO_ARCHIVE')
        self.assertEqual(repeated[refresh.Q3_LOCK_HEADER], first[refresh.Q3_LOCK_HEADER])

    def test_ranges_shift_when_q4_lock_column_is_inserted(self):
        self.assertEqual(refresh.shifted_range('sheet!AO2:AP10', 41), 'sheet!AO2:AQ10')
        self.assertEqual(refresh.shifted_range('sheet!AQ2:AQ10', 41), 'sheet!AR2:AR10')


if __name__ == '__main__':
    unittest.main()
