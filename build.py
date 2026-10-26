#!/usr/bin/env python3
"""
build.py
Inlines slate_data.js into nba_dashboard.html so the page is self-contained.

The template wraps the data script in a sentinel pair:

    <!-- SLATE:START -->
    <script src="slate_data.js"></script>
    <!-- SLATE:END -->

Every run replaces EVERYTHING between the sentinels with a fresh inline block,
so the build is idempotent (no duplicate declarations, no stacking blocks) and
the external <script src> tag is never left alongside the inline copy.
"""

import argparse
import os
import re
import sys

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', default=os.path.dirname(os.path.abspath(__file__)))
args = parser.parse_args()
OUTDIR = args.outdir

ANCHOR     = '// DASHBOARD ENGINE'
HTML_FILE  = os.path.join(OUTDIR, 'nba_dashboard.html')
JS_FILE    = os.path.join(OUTDIR, 'slate_data.js')

SENTINEL_RE = re.compile(r'<!-- SLATE:START -->.*?<!-- SLATE:END -->', re.DOTALL)


def read(path):
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def write(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


if __name__ == '__main__':
    for p in (HTML_FILE, JS_FILE):
        if not os.path.exists(p):
            print(f'[build] missing {p}', file=sys.stderr)
            sys.exit(1)

    html    = read(HTML_FILE)
    js_body = read(JS_FILE)

    if len(SENTINEL_RE.findall(html)) != 1:
        print('[build] expected exactly one <!-- SLATE:START --> ... <!-- SLATE:END --> '
              'block in nba_dashboard.html', file=sys.stderr)
        sys.exit(1)

    # Guard: a literal "</script>" inside the data would end the inline block early
    js_body = js_body.replace('</script', '<\\/script')

    block = (
        '<!-- SLATE:START -->\n'
        f'<script>\n{ANCHOR}\n{js_body}\n</script>\n'
        '<!-- SLATE:END -->'
    )
    # lambda avoids re.sub interpreting backslashes in the replacement text
    html = SENTINEL_RE.sub(lambda m: block, html, count=1)

    write(HTML_FILE, html)
    print(f'[build] inlined slate_data.js into {HTML_FILE}')
