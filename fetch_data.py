#!/usr/bin/env python3
"""
fetch_data.py
Pulls all data needed for the NBA dashboard:
  - Today's games + odds from The Odds API
  - Player prop lines from The Odds API
  - Player season stats from NBA Stats API
  - Team stats from NBA Stats API
Writes raw JSON files to --outdir for odds_fetcher.py to assemble.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone

# ── parse args before anything else ──────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument('--outdir', default=os.path.dirname(os.path.abspath(__file__)))
args = parser.parse_args()
OUTDIR = args.outdir

# ── constants ─────────────────────────────────────────────────────────────────
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

ODDS_API_KEY = os.environ.get('ODDS_API_KEY', '')
SPORT_KEY    = 'basketball_nba'
ODDS_REGIONS = 'us'
ODDS_MARKETS = 'h2h,spreads,totals'
ODDS_FORMAT  = 'american'

PROP_MARKETS = [
    'player_points',
    'player_rebounds',
    'player_assists',
    'player_threes',
    'player_points_rebounds_assists',
]

NBA_STATS_HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Referer': 'https://www.nba.com/',
    'Origin': 'https://www.nba.com',
    'Accept': 'application/json, text/plain, */*',
    'Accept-Language': 'en-US,en;q=0.9',
    'x-nba-stats-origin': 'stats',
    'x-nba-stats-token': 'true',
}

def _season_for(dt):
    """NBA season label for a date: Oct-Dec -> 'YYYY-(YY+1)', Jan-Sep -> '(YYYY-1)-YY'."""
    start = dt.year if dt.month >= 10 else dt.year - 1
    return f'{start}-{(start + 1) % 100:02d}'

CURRENT_SEASON = _season_for(datetime.now(ET))

# ── curl helper ───────────────────────────────────────────────────────────────
def curl_get(url, headers=None, label=''):
    cmd = ['curl', '-s', '-L', '--max-time', '30', url]
    if headers:
        for k, v in headers.items():
            cmd += ['-H', f'{k}: {v}']
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=35)
        if result.returncode != 0:
            print(f'[fetch] curl error {label}: {result.stderr[:200]}', file=sys.stderr)
            return None
        return result.stdout
    except Exception as e:
        print(f'[fetch] exception {label}: {e}', file=sys.stderr)
        return None

def fetch_json(url, headers=None, label=''):
    raw = curl_get(url, headers, label)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        print(f'[fetch] JSON parse error {label}: {e}', file=sys.stderr)
        return None

def write_json(filename, data):
    path = os.path.join(OUTDIR, filename)
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f'[fetch] wrote {path}')


def write_nba(filename, data, label):
    """Write an NBA Stats API payload and log what actually came back (rows + columns)."""
    rows, cols = 0, []
    try:
        rs = (data or {}).get('resultSets', [])
        if rs:
            rows = len(rs[0].get('rowSet', []))
            cols = rs[0].get('headers', [])
    except Exception:
        pass
    status = 'OK' if rows else 'WARNING EMPTY'
    print(f'[fetch] {status} {label}: {rows} rows; cols={cols[:6]}{"..." if len(cols) > 6 else ""} (+{max(len(cols)-6,0)} more)')
    write_json(filename, data or {})

# ── odds api ──────────────────────────────────────────────────────────────────
def fetch_games_and_odds():
    if not ODDS_API_KEY:
        print('[fetch] WARNING: ODDS_API_KEY not set', file=sys.stderr)
        write_json('raw_odds.json', [])
        return

    url = (
        f'https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/odds/'
        f'?apiKey={ODDS_API_KEY}'
        f'&regions={ODDS_REGIONS}'
        f'&markets={ODDS_MARKETS}'
        f'&oddsFormat={ODDS_FORMAT}'
        f'&dateFormat=iso'
    )
    data = fetch_json(url, label='odds/games')
    write_json('raw_odds.json', data or [])

def fetch_props():
    if not ODDS_API_KEY:
        write_json('raw_props.json', [])
        return

    # First get event IDs for today
    raw_odds_path = os.path.join(OUTDIR, 'raw_odds.json')
    try:
        with open(raw_odds_path) as f:
            games = json.load(f)
    except Exception:
        write_json('raw_props.json', [])
        return

    # Filter to today's games (ET)
    today_games = []
    for g in (games or []):
        ct = g.get('commence_time', '')
        if not ct:
            continue
        # Parse ISO and convert to ET
        try:
            dt_utc = datetime.fromisoformat(ct.replace('Z', '+00:00'))
            dt_et = dt_utc.astimezone(ET)
            if dt_et.strftime('%Y-%m-%d') == TODAY_ET:
                today_games.append(g)
        except Exception:
            continue

    all_props = []
    for g in today_games:
        event_id = g.get('id', '')
        if not event_id:
            continue
        for market in PROP_MARKETS:
            url = (
                f'https://api.the-odds-api.com/v4/sports/{SPORT_KEY}/events/{event_id}/odds'
                f'?apiKey={ODDS_API_KEY}'
                f'&regions={ODDS_REGIONS}'
                f'&markets={market}'
                f'&oddsFormat={ODDS_FORMAT}'
                f'&dateFormat=iso'
            )
            data = fetch_json(url, label=f'props/{market}')
            if data:
                all_props.append({'event_id': event_id, 'market': market, 'data': data})

    write_json('raw_props.json', all_props)

# ── nba stats api ─────────────────────────────────────────────────────────────
def fetch_player_stats():
    """Season averages for all players via NBA Stats API LeagueDashPlayerStats."""
    url = (
        f'https://stats.nba.com/stats/leaguedashplayerstats'
        f'?MeasureType=Base'
        f'&PerMode=PerGame'
        f'&PlusMinus=N'
        f'&PaceAdjust=N'
        f'&Rank=N'
        f'&Season={CURRENT_SEASON}'
        f'&SeasonType=Regular+Season'
        f'&GameScope='
        f'&PlayerExperience='
        f'&PlayerPosition='
        f'&StarterBench='
        f'&LastNGames=0'
        f'&Month=0'
        f'&OpponentTeamID=0'
        f'&TeamID=0'
        f'&Conference='
        f'&Division='
        f'&DateFrom='
        f'&DateTo='
    )
    data = fetch_json(url, headers=NBA_STATS_HEADERS, label='player_stats')
    write_nba('raw_player_stats.json', data, 'player_stats')

def fetch_advanced_stats():
    """Advanced stats: usage rate, etc."""
    url = (
        f'https://stats.nba.com/stats/leaguedashplayerstats'
        f'?MeasureType=Advanced'
        f'&PerMode=PerGame'
        f'&PlusMinus=N'
        f'&PaceAdjust=N'
        f'&Rank=N'
        f'&Season={CURRENT_SEASON}'
        f'&SeasonType=Regular+Season'
        f'&GameScope='
        f'&PlayerExperience='
        f'&PlayerPosition='
        f'&StarterBench='
        f'&LastNGames=0'
        f'&Month=0'
        f'&OpponentTeamID=0'
        f'&TeamID=0'
        f'&Conference='
        f'&Division='
        f'&DateFrom='
        f'&DateTo='
    )
    data = fetch_json(url, headers=NBA_STATS_HEADERS, label='advanced_stats')
    write_nba('raw_advanced_stats.json', data, 'advanced_stats')

def fetch_team_stats():
    """Team pace and defensive ratings."""
    url = (
        f'https://stats.nba.com/stats/leaguedashteamstats'
        f'?MeasureType=Advanced'
        f'&PerMode=PerGame'
        f'&PlusMinus=N'
        f'&PaceAdjust=N'
        f'&Rank=N'
        f'&Season={CURRENT_SEASON}'
        f'&SeasonType=Regular+Season'
        f'&GameScope='
        f'&LastNGames=0'
        f'&Month=0'
        f'&OpponentTeamID=0'
        f'&TeamID=0'
        f'&Conference='
        f'&Division='
        f'&DateFrom='
        f'&DateTo='
    )
    data = fetch_json(url, headers=NBA_STATS_HEADERS, label='team_stats')
    write_nba('raw_team_stats.json', data, 'team_stats')

def fetch_opponent_stats():
    """Opponent stats for defensive matchup grading."""
    url = (
        f'https://stats.nba.com/stats/leaguedashteamstats'
        f'?MeasureType=Opponent'
        f'&PerMode=PerGame'
        f'&PlusMinus=N'
        f'&PaceAdjust=N'
        f'&Rank=N'
        f'&Season={CURRENT_SEASON}'
        f'&SeasonType=Regular+Season'
        f'&GameScope='
        f'&LastNGames=0'
        f'&Month=0'
        f'&OpponentTeamID=0'
        f'&TeamID=0'
        f'&Conference='
        f'&Division='
        f'&DateFrom='
        f'&DateTo='
    )
    data = fetch_json(url, headers=NBA_STATS_HEADERS, label='opp_stats')
    write_nba('raw_opp_stats.json', data, 'opp_stats')

def fetch_recent_player_stats(last_n, label_suffix):
    """
    Fetch player stats for last N games (recent form signal).
    Writes raw_player_stats_L{N}.json.
    """
    url = (
        f'https://stats.nba.com/stats/leaguedashplayerstats'
        f'?MeasureType=Base'
        f'&PerMode=PerGame'
        f'&PlusMinus=N'
        f'&PaceAdjust=N'
        f'&Rank=N'
        f'&Season={CURRENT_SEASON}'
        f'&SeasonType=Regular+Season'
        f'&GameScope='
        f'&PlayerExperience='
        f'&PlayerPosition='
        f'&StarterBench='
        f'&LastNGames={last_n}'
        f'&Month=0'
        f'&OpponentTeamID=0'
        f'&TeamID=0'
        f'&Conference='
        f'&Division='
        f'&DateFrom='
        f'&DateTo='
    )
    data = fetch_json(url, headers=NBA_STATS_HEADERS, label=f'player_stats_{label_suffix}')
    write_nba(f'raw_player_stats_{label_suffix}.json', data, f'player_stats_{label_suffix}')

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'[fetch] slate date: {TODAY_ET}')
    print('[fetch] fetching games + odds...')
    fetch_games_and_odds()
    print('[fetch] fetching props...')
    fetch_props()
    print('[fetch] fetching player stats...')
    fetch_player_stats()
    print('[fetch] fetching advanced stats...')
    fetch_advanced_stats()
    print('[fetch] fetching team stats...')
    fetch_team_stats()
    print('[fetch] fetching opponent stats...')
    fetch_opponent_stats()
    print('[fetch] fetching L5 player stats (recent form)...')
    fetch_recent_player_stats(5, 'L5')
    print('[fetch] fetching L10 player stats (recent form)...')
    fetch_recent_player_stats(10, 'L10')
    print('[fetch] done.')
