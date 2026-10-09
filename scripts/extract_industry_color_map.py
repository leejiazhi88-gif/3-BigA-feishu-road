import json
import sys
from pathlib import Path

import openpyxl


SOURCE_SHEET = '2026-09-28（全部）（新）'


def main(source, output):
    sheet = openpyxl.load_workbook(source, data_only=False)[SOURCE_SHEET]
    mappings = {'reference_sheet': SOURCE_SHEET, 'industry_pairs': {}}
    for row in range(2, sheet.max_row + 1):
        l1 = str(sheet.cell(row, 2).value or '').strip()
        l2 = str(sheet.cell(row, 3).value or '').strip()
        if not l1 or not l2:
            continue
        colors = []
        for column in (2, 3):
            cell = sheet.cell(row, column)
            color = cell.fill.fgColor.rgb
            assert cell.fill.fill_type == 'solid' and isinstance(color, str)
            colors.append('#' + color[-6:])
        key = l1 + '\t' + l2
        value = {'sw_l1': l1, 'sw_l2': l2, 'b_color': colors[0], 'c_color': colors[1]}
        previous = mappings['industry_pairs'].setdefault(key, value)
        assert previous == value, (key, previous, value)
    assert len(mappings['industry_pairs']) == 131
    Path(output).write_text(json.dumps(mappings, ensure_ascii=False, indent=2))
    print(json.dumps({
        'reference_sheet': SOURCE_SHEET,
        'industry_pairs': len(mappings['industry_pairs']),
        'sw_l1': len({x['sw_l1'] for x in mappings['industry_pairs'].values()}),
        'sw_l2': len({x['sw_l2'] for x in mappings['industry_pairs'].values()}),
        'colors': sorted({
            color for item in mappings['industry_pairs'].values()
            for color in (item['b_color'], item['c_color'])
        }),
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
