#!/usr/bin/env python3
"""
Performance review from tracker.json: record, calibration (does a 60% pick win 60%?) and closing-line value.
Usage: python3 review.py [tracker.json] [--since YYYY-MM-DD] [--until YYYY-MM-DD]
"""
import json, sys, collections

def dec(o):
    try: o = float(o)
    except (TypeError, ValueError): return None
    if not o: return None
    return 1 + o / 100 if o > 0 else 1 + 100 / -o

def units(p):
    if p['result'] == 'Win':  return (dec(p['odds']) or 1) - 1
    if p['result'] == 'Loss': return -1.0
    return 0.0

def clv(p):
    d0, d1 = dec(p.get('open_odds') or p.get('odds')), dec(p.get('close_odds'))
    m = p.get('meta') or {}
    if not d0 or not d1: return None
    if m.get('line') is not None and p.get('close_line') is not None and float(m['line']) != float(p['close_line']): return None
    return (1 / d1 - 1 / d0) * 100

def main():
    a = sys.argv[1:]
    path = next((x for x in a if x.endswith('.json')), 'tracker.json')
    since = a[a.index('--since') + 1] if '--since' in a else '0000'
    until = a[a.index('--until') + 1] if '--until' in a else '9999'
    ps = [p for p in json.load(open(path))['picks'] if since <= p['date'] <= until]
    done = [p for p in ps if p['result'] in ('Win', 'Loss', 'Push')]
    def line(label, v):
        w, l = sum(p['result'] == 'Win' for p in v), sum(p['result'] == 'Loss' for p in v)
        u = sum(units(p) for p in v)
        print(f'  {label:16} {w}-{l} ({len(v)-w-l}P)  {u:+6.1f}u  ROI {u/max(1,w+l)*100:+5.0f}%')
    print(f'{len(ps)} picks, {len(done)} settled, {len(ps)-len(done)} pending'); line('ALL', done)
    for title, f in (('type', lambda p: p['type']), ('grade', lambda p: p['grade']),
                     ('direction', lambda p: (p.get('meta') or {}).get('direction', '-'))):
        print(f'\nby {title}')
        g = collections.defaultdict(list)
        for p in done: g[f(p)].append(p)
        for k in sorted(g, key=str): line(str(k), g[k])
    cal = [p for p in done if p.get('p') is not None and p['result'] != 'Push']
    print(f'\ncalibration ({len(cal)} picks with a logged model probability)')
    if cal:
        bins = [(0, .35), (.35, .45), (.45, .55), (.55, .65), (.65, 1.01)]
        for lo, hi in bins:
            v = [p for p in cal if lo <= p['p'] < hi]
            if v:
                print(f'  model {lo*100:3.0f}-{min(hi,1)*100:3.0f}%   n={len(v):3d}   predicted {sum(p["p"] for p in v)/len(v)*100:4.1f}%   actual {sum(p["result"]=="Win" for p in v)/len(v)*100:4.1f}%')
        print(f'  overall: predicted {sum(p["p"] for p in cal)/len(cal)*100:.1f}%  actual {sum(p["result"]=="Win" for p in cal)/len(cal)*100:.1f}%')
    c = [(p, clv(p)) for p in ps]; c = [(p, x) for p, x in c if x is not None]
    print(f'\nclosing-line value ({len(c)} picks with a comparable closing price)')
    if c:
        xs = [x for _, x in c]
        print(f'  average CLV {sum(xs)/len(xs):+.2f} pts of win probability; beat the close on {sum(x>0 for x in xs)}/{len(xs)}')

if __name__ == '__main__':
    main()
