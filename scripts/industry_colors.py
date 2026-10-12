import json
from pathlib import Path


def column_name(index):
    result = []
    while index:
        index, remainder = divmod(index - 1, 26)
        result.append(chr(65 + remainder))
    return ''.join(reversed(result))


def style_payload(values, sheet_id, mapping_path, clear_to=500,
                  l1_index=1, l2_index=2, column_count=48,
                  excluded_columns=None):
    mapping = json.loads(Path(mapping_path).read_text())
    excluded_columns = set(excluded_columns or [])
    rows = [list(row) for row in values[1:] if row and row[0]]
    groups = {}
    missing = set()

    for row_number, row in enumerate(rows, 2):
        row += [''] * max(0, max(l1_index, l2_index) + 1 - len(row))
        l1, l2 = str(row[l1_index] or '').strip(), str(row[l2_index] or '').strip()
        pair = mapping['industry_pairs'].get(l1 + '\t' + l2)
        if pair is None:
            missing.add((l1, l2))
            continue
        assert pair['b_color'] == pair['c_color'], (l1, l2, pair)
        color = pair['b_color']
        groups.setdefault(color, []).extend(
            f'{sheet_id}!{column_name(column)}{row_number}:{column_name(column)}{row_number}'
            for column in range(1, column_count + 1)
            if column not in excluded_columns
        )
    assert not missing, missing

    styles = []
    for color, ranges in groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({'ranges': ranges[start:start + 100], 'style': {'backColor': color}})
    last_row = len(rows) + 1
    if last_row < clear_to:
        blank_ranges = [
            f'{sheet_id}!{column_name(column)}{row}:{column_name(column)}{row}'
            for row in range(last_row + 1, clear_to + 1)
            for column in range(1, column_count + 1)
            if column not in excluded_columns
        ]
        for start in range(0, len(blank_ranges), 100):
            styles.append({
                'ranges': blank_ranges[start:start + 100],
                'style': {'backColor': '#FFFFFF'},
            })
    return styles, {
        'rows': len(rows),
        'sw_l1_categories': len({str(row[l1_index]) for row in rows}),
        'sw_l2_categories': len({str(row[l2_index]) for row in rows}),
        'colors_used': len(groups),
        'columns_colored': f'A:{column_name(column_count)}',
        'excluded_columns': sorted(excluded_columns),
        'reference_sheet': mapping['reference_sheet'],
    }
