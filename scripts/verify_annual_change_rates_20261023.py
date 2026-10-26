#!/usr/bin/env python3
"""Export and verify the annual forecast change-rate values and styles."""
from __future__ import annotations

import json
import math
from pathlib import Path

import openpyxl

import verify_annual_change_colors_20261023 as export_helper

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / 'outputs' / 'annual-change-color-fix' / '2026-10-23-all.xlsx'
AUDIT = ROOT / 'exports' / 'refresh_20261023' / 'annual_change_rates.json'
RATE_COLUMNS = {2026: 'S', 2027: 'T', 2028: 'U'}


def main():
    export_helper.OUTPUT = OUTPUT
    export_helper.export_workbook(export_helper.token())
    workbook = openpyxl.load_workbook(OUTPUT, data_only=False)
    sheet = workbook['2026-10-23（全部）']
    value_mismatches = []
    color_mismatches = []
    format_mismatches = []
    checked = 0
    for row in range(2, 462):
        expected = export_helper.re.findall(
            r'(20\d{2})年（旧值[^，]*，(新增预测|[-+]?\d+(?:\.\d+)?%)）',
            str(sheet[f'R{row}'].value or ''),
        )
        expected_by_year = {
            int(year): None if movement == '新增预测'
            else round(float(movement.rstrip('%')) / 100, 6)
            for year, movement in expected
        }
        for year, column in RATE_COLUMNS.items():
            cell = sheet[f'{column}{row}']
            expected_value = expected_by_year.get(year)
            actual_value = cell.value
            if expected_value is None:
                if actual_value not in (None, ''):
                    value_mismatches.append((cell.coordinate, expected_value, actual_value))
                continue
            checked += 1
            if not isinstance(actual_value, (int, float)) or not math.isclose(
                    actual_value, expected_value, abs_tol=1e-9):
                value_mismatches.append((cell.coordinate, expected_value, actual_value))
            expected_color = '00B050' if expected_value > 0 else 'C00000' if expected_value < 0 else '000000'
            actual_color = export_helper.actual_color(cell)
            if actual_color != expected_color:
                color_mismatches.append((cell.coordinate, expected_color, actual_color))
            if cell.number_format != '0.00%':
                format_mismatches.append((cell.coordinate, cell.number_format))

    assert not value_mismatches, value_mismatches[:10]
    assert not color_mismatches, color_mismatches[:10]
    assert not format_mismatches, format_mismatches[:10]
    audit = json.loads(AUDIT.read_text())
    audit.update({
        'export_file': str(OUTPUT.relative_to(ROOT)),
        'nonempty_values_checked': checked,
        'value_mismatches': 0,
        'style_mismatches': 0,
        'number_format_mismatches': 0,
        'export_verified': True,
    })
    AUDIT.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({key: audit[key] for key in (
        'nonempty_values_checked', 'value_mismatches', 'style_mismatches',
        'number_format_mismatches', 'export_verified')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
