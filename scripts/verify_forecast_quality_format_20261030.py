"""Inspect native Feishu exports; never rewrite their formatting."""
from copy import copy
import json
from pathlib import Path
import re
import warnings
import openpyxl

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / 'work/forecast-quality-20261030'
TARGET = '2026-10-29（全部）'


def main():
    warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')
    before = openpyxl.load_workbook(WORK / 'before.xlsx')
    after = openpyxl.load_workbook(ROOT / 'outputs/forecast_quality_20261030/2026-10-29-all-corrected.xlsx')
    assert before.sheetnames == after.sheetnames
    ranges = json.loads((WORK / 'write_ranges.json').read_text())
    writable = {re.search(r'!([A-Z]+)', r['range'])[1] for r in ranges}
    font_columns = {'J','K','L','R','S','T','U','W','X','Y','AN','AP','AR','AS'}
    compared = 0
    changed_fonts = 0
    cache = {}
    export_dimension_ratios = {'width': set(), 'height': set()}
    for old in before:
        new = after[old.title]
        assert old.merged_cells == new.merged_cells
        for key in set(old._cells) | set(new._cells):
            a, b = old.cell(*key), new.cell(*key)
            writable_cell = old.title == TARGET and 2 <= a.row <= 463 and a.column_letter in writable
            if not writable_cell:
                assert a.value == b.value, (old.title, a.coordinate, 'value')
            pair = (a.style_id, b.style_id)
            if pair not in cache:
                cache[pair] = [attr for attr in ('fill','font','alignment','border','number_format','protection')
                               if copy(getattr(a, attr)) != copy(getattr(b, attr))]
            for attr in cache[pair]:
                assert attr == 'font' and writable_cell and a.column_letter in font_columns, (old.title,a.coordinate,attr)
                fa, fb = copy(a.font), copy(b.font)
                fa.color = fb.color
                assert fa == fb, (a.coordinate,'noncolor font property')
                changed_fonts += 1
            compared += 1
        for key in set(old.column_dimensions) | set(new.column_dimensions):
            x, y = old.column_dimensions[key].width, new.column_dimensions[key].width
            if x != y:
                assert x and y
                export_dimension_ratios['width'].add(round(y/x,6))
            for attr in ('hidden','outlineLevel','collapsed','min','max'):
                assert getattr(old.column_dimensions[key],attr) == getattr(new.column_dimensions[key],attr), (old.title,key,attr)
        for key in set(old.row_dimensions) | set(new.row_dimensions):
            x, y = old.row_dimensions[key].height, new.row_dimensions[key].height
            if x != y:
                assert x and y
                export_dimension_ratios['height'].add(round(y/x,6))
            for attr in ('hidden','outlineLevel','collapsed'):
                assert getattr(old.row_dimensions[key],attr) == getattr(new.row_dimensions[key],attr), (old.title,key,attr)
    sheet = after[TARGET]
    def color(cell):
        c = cell.font.color
        return str(c.rgb)[-6:].upper() if c and c.type == 'rgb' else '000000'
    color_checks = 0
    for row in range(2,464):
        text = str(sheet[f'R{row}'].value or '')
        entries = re.findall(r'(20\d{2})年（旧值[^，]*，(新增预测|[-+]?\d+(?:\.\d+)?%)）',text)
        movement = min(entries)[1] if entries else '新增预测'
        value = 0 if movement == '新增预测' else float(movement.rstrip('%'))
        assert color(sheet[f'R{row}']) == ('00B050' if value>0 else 'C00000' if value<0 else '000000'), (row,'R')
        color_checks += 1
        for col in ('S','T','U'):
            value = sheet[f'{col}{row}'].value or 0
            assert color(sheet[f'{col}{row}']) == ('00B050' if value>0 else 'C00000' if value<0 else '000000'), (row,col)
            color_checks += 1
        for col in ('J','K','L','W','X','Y'):
            v = sheet[f'{col}{row}'].value
            expected = '000000'
            if isinstance(v,(int,float)):
                if col in ('J','K','L'):
                    expected = '00B050' if v<30 else 'C00000' if v>50 else '000000'
                else:
                    expected = 'C00000' if v<=0 else '00B050' if v>=.3 else '0070C0' if v>=.1 else '000000'
            assert color(sheet[f'{col}{row}']) == expected, (row,col,v,color(sheet[f'{col}{row}']),expected)
            color_checks += 1
    # Feishu's two native exports used different global pixel/unit conversions,
    # including on untouched sheets. Report this rather than claiming byte equality.
    assert all(len(ratios) <= 1 for ratios in export_dimension_ratios.values()), export_dimension_ratios
    result = dict(sheets_checked=len(before.sheetnames),cells_checked=compared,
                  font_colors_changed=changed_fonts,rule_color_checks=color_checks,
                  fills_preserved=True,number_formats_preserved=True,
                  export_dimension_scale={k:sorted(v) for k,v in export_dimension_ratios.items()},
                  notes_and_locks_preserved=True,other_sheet_values_and_cell_styles_preserved=True)
    (ROOT/'exports/forecast_quality_20261030/format_verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False))


if __name__ == '__main__':
    main()
