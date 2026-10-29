#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch unadjusted ETF prices and distributions independently of project data."""
import datetime
import hashlib
import json
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
END = sys.argv[1] if len(sys.argv) > 1 else '2026-10-29'
CODES = {'510300': '1', '159915': '0', '513100': '1', '513500': '1', '518880': '1'}


def fetch(url):
    for attempt in range(3):
        try:
            return subprocess.run(['curl', '--fail', '--silent', '--show-error', '--max-time', '30',
                                   '-H', 'User-Agent: Mozilla/5.0', url], check=True, capture_output=True).stdout
        except Exception:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


class Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tables, self.table, self.row, self.cell = [], None, None, None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            self.table = []
        elif tag == 'tr' and self.table is not None:
            self.row = []
        elif tag in ('td', 'th') and self.row is not None:
            self.cell = []

    def handle_data(self, data):
        if self.cell is not None:
            self.cell.append(data)

    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip())
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.table.append(self.row)
            self.row = None
        elif tag == 'table' and self.table is not None:
            self.tables.append(self.table)
            self.table = None


def main():
    prices, actions, metadata = {}, {}, {}
    for code, market in CODES.items():
        symbol = ('sh' if market == '1' else 'sz') + code
        url = ('https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/'
               f'CN_MarketData.getKLineData?symbol={symbol}&scale=240&ma=no&datalen=8000')
        body = fetch(url)
        payload = json.loads(body)
        rows = []
        for record in payload:
            day = record['day']
            if day < '2014-01-01' or day > END:
                continue
            vals = [float(record[field]) for field in ('open', 'close', 'high', 'low')]
            assert min(vals) > 0
            rows.append([day, vals + [int(record['volume'])]])
        assert rows == sorted(rows) and len({r[0] for r in rows}) == len(rows)
        prices[code] = rows
        action_url = f'https://fundf10.eastmoney.com/fhsp_{code}.html'
        body_actions = fetch(action_url)
        parser = Tables()
        parser.feed(body_actions.decode('utf-8', errors='replace'))
        dividends, splits = [], []
        for table in parser.tables:
            if table and '除息日' in table[0] and '分红发放日' in table[0]:
                for row in table[1:]:
                    if len(row) >= 5 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[2]):
                        amount = re.search(r'派现金([\d.]+)元', row[3])
                        if not amount:
                            raise ValueError((code, row))
                        dividends.append({'record_date': row[1], 'ex_date': row[2], 'pay_date': row[4],
                                          'amount_per_share': float(amount.group(1)) / 10})
            if table and '拆分折算日' in table[0]:
                for row in table[1:]:
                    if len(row) >= 4 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[1]):
                        ratio = re.fullmatch(r'1:([\d.]+)', row[3])
                        if not ratio:
                            raise ValueError((code, row))
                        splits.append({'date': row[1], 'ratio': float(ratio.group(1)), 'type': row[2]})
        actions[code] = {'dividends': dividends, 'splits': splits}
        metadata[code] = {'price_source': url, 'price_response_sha256': hashlib.sha256(body).hexdigest(),
                          'action_source': action_url, 'action_response_sha256': hashlib.sha256(body_actions).hexdigest(),
                          'rows': len(rows), 'first': rows[0][0], 'last': rows[-1][0]}
        print(code, metadata[code]['first'], metadata[code]['last'], 'rows', len(rows),
              'dividends', len(dividends), 'splits', len(splits), flush=True)
    result = {'fetched_at': datetime.datetime.now().astimezone().isoformat(), 'end': END,
              'metadata': metadata, 'prices': prices, 'actions': actions}
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else ROOT / 'fresh_market_data_20261029.json'
    output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    print('saved', output)


if __name__ == '__main__':
    main()
