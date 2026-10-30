"""Set every allocated row in one Feishu sheet to a pixel height."""
import argparse
import json
from datetime import datetime
from pathlib import Path
from business_composition import feishu_client as feishu


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('sheet_id')
    parser.add_argument('height', type=int)
    parser.add_argument('--audit', type=Path, required=True)
    args = parser.parse_args()
    if args.height <= 0:
        parser.error('height must be positive')
    token = feishu.get_token()
    metadata = feishu.metadata(token, args.sheet_id)
    count = metadata['grid_properties']['row_count']
    before = feishu.read_range(token, f'{args.sheet_id}!A1:BK{count}')
    cf_before = feishu.condition_formats(token, args.sheet_id)
    body = {
        'dimension': {'sheetId': args.sheet_id, 'majorDimension': 'ROWS',
                      'startIndex': 1, 'endIndex': count},
        'dimensionProperties': {'fixedSize': args.height},
    }
    result = feishu.api(feishu.BASE + '/dimension_range', token, 'PUT', body)
    assert feishu.read_range(token, f'{args.sheet_id}!A1:BK{count}') == before
    assert feishu.condition_formats(token, args.sheet_id)['data'] == cf_before['data']
    audit = {'sheet_id': args.sheet_id, 'title': metadata['title'],
             'rows': count, 'height_px': args.height, 'timestamp': datetime.now().isoformat(),
             'request': body, 'response': result, 'values_preserved': True,
             'conditional_formats_preserved': True}
    args.audit.parent.mkdir(parents=True, exist_ok=True)
    args.audit.write_text(json.dumps(audit, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    main()
