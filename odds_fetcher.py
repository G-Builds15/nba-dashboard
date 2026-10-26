#!/usr/bin/env python3
"""
odds_fetcher.py
Pure file assembler — no network calls.
Reads raw JSON files written by fetch_data.py and assembles
a clean odds_data.json for slate_builder.py to consume.
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

parser = argparse.ArgumentParser()
parser.add_argument('--outdir', default=os.path.dirname(os.path.abspath(__file__)))
args = parser.parse_args()
OUTDIR = args.outdir

# Use fixed UTC offsets: EDT (summer) = -4, EST (winter) = -5
# NBA season spans both; pick the correct offset for today's wall-clock date
_now_utc = datetime.now(timezone.utc)
_naive   = _now_utc.replace(tzinfo=None)
# DST in US: 2nd Sun Mar → 1st Sun Nov
def _is_edt(dt):
    year = dt.year
    # 2nd Sunday in March
    mar = datetime(year, 3, 8)
    mar_sun = mar + timedelta(days=(6 - mar.weekday()) % 7)
    # 1st Sunday in November
    nov = datetime(year, 11, 1)
    nov_sun = nov + timedelta(days=(6 - nov.weekday()) % 7)
    return mar_sun <= dt.replace(tzinfo=None) < nov_sun
ET = timezone(timedelta(hours=-4 if _is_edt(_naive) else -5))
TODAY_ET = datetime.now(ET).strftime('%Y-%m-%d')

PROP_MARKET_MAP = {
    'player_points':                    {'type': 'pts',  'label': 'pts'},
    'player_rebounds':                  {'type': 'reb',  'label': 'reb'},
    'player_assists':                   {'type': 'ast',  'label': 'ast'},
    'player_threes':                    {'type': '3pm',  'label': '3PM'},
    'player_points_rebounds_assists':   {'type': 'pra',  'label': 'PRA'},
}

# Best book priority for line selection
BOOK_PRIORITY = ['draftkings', 'fanduel', 'betmgm', 'caesars', 'pointsbet']

def load_json(filename):
    path = os.path.join(OUTDIR, filename)
    if not os.path.exists(path):
        print(f'[odds_fetcher] missing: {path}', file=sys.stderr)
        return None
    with open(path) as f:
        try:
            return json.load(f)
        except json.JSONDecodeError as e:
            print(f'[odds_fetcher] JSON error {filename}: {e}', file=sys.stderr)
            return None

def write_json(filename, data):
    path = os.path.join(OUTDIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'[odds_fetcher] wrote {path}')

def best_odds(bookmakers, market_key, outcome_name):
    """Pick best available odds for an outcome across books."""
    best = None
    for priority_book in BOOK_PRIORITY:
        for book in bookmakers:
            if book.get('key', '').lower() != priority_book:
                continue
            for market in book.get('markets', []):
                if market.get('key') != market_key:
                    continue
                for outcome in market.get('outcomes', []):
                    if outcome.get('name', '').lower() == outcome_name.lower():
                        if best is None:
                            best = outcome.get('price')
                        else:
                            # Prefer better odds for bettor
                            if outcome.get('price', -999) > best:
                                best = outcome.get('price')
    return best

def parse_games(raw_odds):
    """Parse raw odds API response into structured game objects."""
    games = []
    for g in (raw_odds or []):
        ct = g.get('commence_time', '')
        try:
            dt_utc = datetime.fromisoformat(ct.replace('Z', '+00:00'))
            dt_et = dt_utc.astimezone(ET)
            if dt_et.strftime('%Y-%m-%d') != TODAY_ET:
                continue
            game_time_str = dt_et.strftime('%-I:%M %p ET')
        except Exception:
            continue

        home = g.get('home_team', '')
        away = g.get('away_team', '')
        books = g.get('bookmakers', [])

        # Spread
        home_spread = best_odds(books, 'spreads', home)
        away_spread = best_odds(books, 'spreads', away)
        spread_line_home = None
        spread_line_away = None
        for book in books:
            for market in book.get('markets', []):
                if market.get('key') == 'spreads':
                    for outcome in market.get('outcomes', []):
                        if outcome.get('name') == home:
                            spread_line_home = outcome.get('point')
                        elif outcome.get('name') == away:
                            spread_line_away = outcome.get('point')
                    break
            if spread_line_home is not None:
                break

        # Total
        over_odds = best_odds(books, 'totals', 'Over')
        under_odds = best_odds(books, 'totals', 'Under')
        total_line = None
        for book in books:
            for market in book.get('markets', []):
                if market.get('key') == 'totals':
                    for outcome in market.get('outcomes', []):
                        if outcome.get('name') == 'Over':
                            total_line = outcome.get('point')
                    break
            if total_line is not None:
                break

        # Moneyline
        home_ml = best_odds(books, 'h2h', home)
        away_ml = best_odds(books, 'h2h', away)

        games.append({
            'event_id':        g.get('id', ''),
            'home_team':       home,
            'away_team':       away,
            'game_time':       game_time_str,
            'commence_time':   ct,
            'spread_home':     spread_line_home,
            'spread_away':     spread_line_away,
            'odds_spread_home': home_spread,
            'odds_spread_away': away_spread,
            'total_line':      total_line,
            'odds_over':       over_odds,
            'odds_under':      under_odds,
            'odds_ml_home':    home_ml,
            'odds_ml_away':    away_ml,
        })
    return games

def parse_props(raw_props_list, game_event_ids):
    """Parse raw props API responses into per-player prop objects."""
    props_by_event = {}
    for entry in (raw_props_list or []):
        event_id = entry.get('event_id', '')
        if event_id not in game_event_ids:
            continue
        market_key = entry.get('market', '')
        market_info = PROP_MARKET_MAP.get(market_key, {})
        data = entry.get('data', {})

        for book in data.get('bookmakers', []):
            for market in book.get('markets', []):
                if market.get('key') != market_key:
                    continue
                for outcome in market.get('outcomes', []):
                    # Player prop outcome structure varies by book:
                    # Some: name="Over", description="Player Name"
                    # Some: name="Player Name", description="Over"
                    # Normalise: player is the longer/non-direction value
                    raw_name = outcome.get('name', '')
                    raw_desc = outcome.get('description', '')
                    if raw_name in ('Over', 'Under'):
                        direction = raw_name
                        player    = raw_desc
                    elif raw_desc in ('Over', 'Under'):
                        direction = raw_desc
                        player    = raw_name
                    else:
                        # Fallback: description is player, name is direction
                        player    = raw_desc or raw_name
                        direction = raw_name if raw_name in ('Over','Under') else ''

                    line = outcome.get('point')
                    odds = outcome.get('price')

                    if not player or line is None:
                        continue

                    key = (event_id, player, market_key, direction)
                    if event_id not in props_by_event:
                        props_by_event[event_id] = {}
                    if key not in props_by_event[event_id]:
                        props_by_event[event_id][key] = {
                            'event_id':    event_id,
                            'player_name': player,
                            'prop_type':   market_info.get('type', market_key),
                            'prop_label':  market_info.get('label', market_key),
                            'direction':   direction,
                            'line':        line,
                            'odds':        odds,
                        }
    # Flatten
    result = {}
    for eid, props in props_by_event.items():
        result[eid] = list(props.values())
    return result

if __name__ == '__main__':
    print(f'[odds_fetcher] assembling for {TODAY_ET}')

    raw_odds = load_json('raw_odds.json') or []
    raw_props = load_json('raw_props.json') or []

    games = parse_games(raw_odds)
    print(f'[odds_fetcher] {len(games)} games today')

    event_ids = {g['event_id'] for g in games}
    props_by_event = parse_props(raw_props, event_ids)

    output = {
        'slate_date': TODAY_ET,
        'games': games,
        'props_by_event': props_by_event,
    }
    write_json('odds_data.json', output)
    print('[odds_fetcher] done.')
