"""Move native copied rows before writing values, preserving per-company styles."""
from business_composition import feishu_client as f


def align(token, sheet_id, source, desired):
    index = source[0].index('代码')
    current = [r[index] if r and r[0] else f'__blank_{i}'
               for i, r in enumerate(source[1:])]
    wanted = [r[index] for r in desired[1:] if r and r[0]]
    old_codes = {r[index] for r in source[1:] if r and r[0]}
    assert old_codes <= set(wanted), 'Cannot discard copied companies'
    new = [c for c in wanted if c not in old_codes]
    blanks = iter(c for c in current if c.startswith('__blank_'))
    replacements = {c: next(blanks) for c in new}
    order = [replacements.get(c, c) for c in wanted]
    assert len(set(order)) == len(order)
    moves = 0
    for i, code in enumerate(order):
        if current[i] == code:
            continue
        j = current.index(code, i + 1)
        length = 1
        while (j + length < len(current) and i + length < len(order)
               and current[j + length] == order[i + length]):
            length += 1
        f.api(f'sheets/v3/spreadsheets/{f.SPREADSHEET}/sheets/{sheet_id}/move_dimension',
              token, 'POST', {'source': {'major_dimension': 'ROWS',
                  'start_index': j + 1, 'end_index': j + length},
                  'destination_index': i + 1})
        block = current[j:j + length]
        del current[j:j + length]
        current[i:i] = block
        moves += 1
    assert current[:len(order)] == order
    actual = f.read_range(token, f'{sheet_id}!A1:BL{len(source)}')
    for i, code in enumerate(wanted, 1):
        assert (actual[i][index] if actual[i] and actual[i][0] else '') == (code if code in old_codes else '')
    print(f'Preserved native row styles through {moves} row moves', flush=True)
    return {'moves': moves, 'existing': len(old_codes), 'new': new}
