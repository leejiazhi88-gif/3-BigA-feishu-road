import json
from pathlib import Path


def style_payload(values, sheet_id, mapping_path, clear_to=500):
    mapping = json.loads(Path(mapping_path).read_text())
    rows = [list(row) for row in values[1:] if row and row[0]]
    groups = {}
    missing = set()

    for row_number, row in enumerate(rows, 2):
        row += [''] * max(0, 3 - len(row))
        l1, l2 = str(row[1] or '').strip(), str(row[2] or '').strip()
        pair = mapping['industry_pairs'].get(l1 + '\t' + l2)
        if pair is None:
            missing.add((l1, l2))
            continue
        for column, color_key in (('B', 'b_color'), ('C', 'c_color')):
            color = pair[color_key]
            groups.setdefault(color, []).append(f'{sheet_id}!{column}{row_number}:{column}{row_number}')
    assert not missing, missing

    styles = []
    for color, ranges in groups.items():
        for start in range(0, len(ranges), 100):
            styles.append({'ranges': ranges[start:start + 100], 'style': {'backColor': color}})
    last_row = len(rows) + 1
    if last_row < clear_to:
        styles.append({
            'ranges': [f'{sheet_id}!B{last_row + 1}:C{clear_to}'],
            'style': {'backColor': '#FFFFFF'},
        })
    return styles, {
        'rows': len(rows),
        'sw_l1_categories': len({str(row[1]) for row in rows}),
        'sw_l2_categories': len({str(row[2]) for row in rows}),
        'colors_used': len(groups),
        'reference_sheet': mapping['reference_sheet'],
    }
