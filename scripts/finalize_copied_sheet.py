"""Finish a full Feishu UI sheet copy with values and value-dependent colors.

Run after duplicating the previous sheet in Feishu. The copy must already have
its conditional formatting rules. Payload comes from refresh_all_* prepare.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import refresh_all_20261012 as refresh
from business_composition import feishu_client as feishu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sheet-id', required=True, help='ID of the full UI copy')
    parser.add_argument('--payload', required=True, type=Path,
                        help='payload.json made by the refresh prepare step')
    parser.add_argument('--note-styles', required=True, type=Path,
                        help='B/C font and fill styles keyed by stock code')
    parser.add_argument('--expected-rules', required=True, type=int)
    args = parser.parse_args()
    if args.expected_rules <= 0:
        parser.error('--expected-rules must be positive')

    payload = json.loads(args.payload.read_text(encoding='utf-8'))
    values = payload['valueRange']['values']
    headers = values[0]
    assert headers[8:12] == [
        'PE(TTM)', '2026 PE(预测)', '2027 PE(预测)', '2028 PE(预测)'
    ], 'I:L must be the four PE columns'
    width = len(headers)
    code_index = headers.index('代码')
    visible = [headers] + [row for row in values[1:]
                           if len(row) > code_index and row[code_index]]
    assert len(visible) > 1
    codes = [str(row[code_index]) for row in visible[1:]]
    assert len(codes) == len(set(codes)), 'Duplicate stock codes'

    token = feishu.get_token()
    sheet_id = args.sheet_id
    def rule_count():
        return len(feishu.condition_formats(token, sheet_id)
                   ['data']['sheet_condition_formats'])
    assert rule_count() == args.expected_rules, 'Full copy lost conditional formatting'

    # Only values go into the copied sheet; the complete UI copy owns its
    # conditional formatting, number formats, dimensions and frozen panes.
    for start in range(0, len(values), 100):
        chunk = values[start:start + 100]
        feishu.api(feishu.BASE + '/values', token, 'PUT', {
            'valueRange': {'range': f'{sheet_id}!A{start + 1}:'
                           f'{refresh.column_name(width)}{start + len(chunk)}',
                           'values': chunk}})

    refresh.TARGET = sheet_id
    refresh.PERSONAL_NOTE_STYLE_MAP = args.note_styles
    dynamic_styles = refresh.font_style_payload(visible)
    note_styles = refresh.personal_note_style_payload(visible)
    annual_styles = refresh.annual_change_style_payload(visible)
    annual_rate_styles = refresh.annual_change_rate_style_payload(visible)
    assert note_styles, 'B/C stock-specific note styles are missing'
    pe_cells = {f'{sheet_id}!{col}{row}:{col}{row}'
                for row in range(2, len(visible) + 1) for col in 'IJKL'}
    styled_cells = {cell for item in dynamic_styles for cell in item['ranges']}
    assert pe_cells <= styled_cells, 'PE style coverage is incomplete'
    assert len(headers) >= 53 and headers[39] == '2026Q1净利润(亿元)', 'AN:BA layout changed'
    quarter_columns = [refresh.column_name(i) for i in range(40, 54)]
    quarter_cells = {f'{sheet_id}!{col}{row}:{col}{row}'
                     for row in range(2, len(visible) + 1) for col in quarter_columns}
    assert quarter_cells <= styled_cells, 'Quarter comparison style coverage is incomplete'
    annual_cells = {f'{sheet_id}!{col}{row}:{col}{row}'
                    for row in range(2, len(visible) + 1) for col in 'RSTU'}
    annual_styled = {cell for item in annual_styles + annual_rate_styles
                     for cell in item['ranges']}
    assert annual_cells <= annual_styled, 'R:U style coverage is incomplete'
    for styles in (dynamic_styles, note_styles, annual_styles, annual_rate_styles):
        for start in range(0, len(styles), 30):
            feishu.api(feishu.BASE + '/styles_batch_update', token, 'PUT',
                       {'data': styles[start:start + 30]})

    actual = feishu.read_range(
        token, f'{sheet_id}!A1:{refresh.column_name(width)}{len(values)}')
    assert len(actual) == len(values), 'Row count changed'
    for row_number, (expected_row, actual_row) in enumerate(zip(values, actual), 1):
        for col_number, (expected, got) in enumerate(zip(
                expected_row + [''] * (width - len(expected_row)),
                actual_row + [''] * (width - len(actual_row))), 1):
            assert refresh.equivalent(expected, got), (row_number, col_number, expected, got)
    assert rule_count() == args.expected_rules, 'Conditional formatting changed'
    print(json.dumps({'sheet_id': sheet_id, 'stocks': len(codes),
                      'pe_cells_colored': len(pe_cells),
                      'annual_change_cells_colored': len(annual_cells),
                      'quarter_cells_colored': len(quarter_cells),
                      'note_cells_colored': len(codes) * 2,
                      'conditional_format_rules': args.expected_rules},
                     ensure_ascii=False))


if __name__ == '__main__':
    main()

