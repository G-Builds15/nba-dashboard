#!/usr/bin/env python3
"""
fetch_data.py
Pulls all data needed for the NBA dashboard:
  - Today's games + odds from The Odds API
  - Player prop lines from The Odds API
  - Player season stats, team stats and recent form (game logs) from ESPN's public JSON
    endpoints (stats.nba.com blocks GitHub-hosted runners)
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

# ── ESPN stats ────────────────────────────────────────────────────────────────
# stats.nba.com drops requests from GitHub-hosted runners (confirmed: every call
# times out), so player/team stats come from ESPN's public JSON endpoints instead.
# Each function writes the same table layout the grader already reads
# ({"resultSets": [{"headers": [...], "rowSet": [...]}]}).
ESPN_SEASON  = int(CURRENT_SEASON.split('-')[0]) + 1      # ESPN labels a season by its END year
ESPN_HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                              'Chrome/124 Safari/537.36'}
ESPN_SITE    = 'https://site.api.espn.com/apis/site/v2/sports/basketball/nba'
ESPN_COMMON  = 'https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba'
MAX_GAMELOGS = 300      # cap on per-player game-log calls (only players with a prop today)
WORKERS      = 8

_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}

def _norm_name(name):
    """Same rules as slate_builder.normalize_player, so prop names match ESPN names."""
    import unicodedata
    n = unicodedata.normalize('NFKD', name or '').encode('ascii', 'ignore').decode().lower().strip()
    n = n.replace('.', '').replace("'", '').replace(',', '').replace('-', ' ')
    parts = [p for p in n.split() if p]
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return ' '.join(parts)

def _num(v, default=0.0):
    if isinstance(v, dict):
        v = v.get('value', v.get('displayValue'))
    try:
        return float(str(v).replace(',', ''))
    except (TypeError, ValueError):
        return default

def write_table(filename, headers, rows, label):
    status = 'OK' if rows else 'WARNING EMPTY'
    print(f'[fetch] {status} {label}: {len(rows)} rows; cols={headers}')
    write_json(filename, {'resultSets': [{'name': label, 'headers': headers, 'rowSet': rows}]})

def _pmap(fn, items):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        return list(ex.map(fn, items))

def fetch_espn_teams():
    """{espn_team_id: displayName}"""
    data = fetch_json(f'{ESPN_SITE}/teams', ESPN_HEADERS, 'espn_teams')
    out = {}
    try:
        for t in data['sports'][0]['leagues'][0]['teams']:
            out[str(t['team']['id'])] = t['team']['displayName']
    except Exception as e:
        print(f'[fetch] WARNING could not parse ESPN team list: {e}', file=sys.stderr)
    print(f'[fetch] espn teams: {len(out)}')
    return out

def fetch_espn_team_totals(team_names):
    """Per-game team averages {team_id: {stat_name: value}} from the team statistics endpoint."""
    def one(tid):
        d = fetch_json(f'{ESPN_SITE}/teams/{tid}/statistics', ESPN_HEADERS, f'team_stats/{tid}')
        flat = {}
        try:
            for c in d['results']['stats']['categories']:
                for s in c.get('stats', []):
                    flat[s.get('name')] = s.get('value')
        except Exception:
            pass
        return tid, flat
    return {tid: flat for tid, flat in _pmap(one, list(team_names)) if flat}

def fetch_espn_points_allowed():
    """
    Points allowed per game, season to date, from completed regular-season games.
    One scoreboard call per day (the plain, well-supported form of the endpoint).
    {team_id: (points_allowed_per_game, games)}
    """
    from datetime import date as _date
    today  = datetime.now(ET).date()
    first  = _date(ESPN_SEASON - 1, 10, 1)
    days   = [first + timedelta(days=i) for i in range((today - first).days + 1)]
    pages  = _pmap(lambda d: fetch_json(f"{ESPN_SITE}/scoreboard?dates={d.strftime('%Y%m%d')}&limit=100",
                                        ESPN_HEADERS, f'scoreboard/{d}'), days)
    agg, seen_ids = {}, set()
    seen = used = not_final = preseason = 0
    for page in pages:
        for ev in (page or {}).get('events', []):
            if ev.get('id') in seen_ids:
                continue
            seen_ids.add(ev.get('id'))
            seen += 1
            stype = (ev.get('season') or {}).get('type')
            if stype is not None and stype != 2:        # skip preseason / playoffs / other
                preseason += 1
                continue
            comp = (ev.get('competitions') or [{}])[0]
            stt  = (comp.get('status') or ev.get('status') or {}).get('type') or {}
            if not (stt.get('completed') or stt.get('state') == 'post'):
                not_final += 1
                continue
            cs = comp.get('competitors') or []
            if len(cs) != 2:
                continue
            try:
                a, b = cs
                sa, sb = _num(a.get('score')), _num(b.get('score'))
                ia, ib = str(a['team']['id']), str(b['team']['id'])
            except Exception:
                continue
            if not (sa or sb):
                continue
            used += 1
            for tid, pa in ((ia, sb), (ib, sa)):
                tot = agg.setdefault(tid, [0.0, 0])
                tot[0] += pa
                tot[1] += 1
    print(f'[fetch] espn scoreboard: {len(days)} days, {seen} events, {used} final regular-season games used '
          f'({preseason} non-regular-season, {not_final} not final)')
    if not used:
        sample = next((p for p in pages if p), None)
        print(f'[fetch] WARNING no usable games; scoreboard top-level keys: {list((sample or {}).keys())}',
              file=sys.stderr)
    return {tid: (t[0] / t[1], t[1]) for tid, t in agg.items() if t[1]}

def build_team_tables(team_names, totals, allowed):
    team_rows, opp_rows = [], []
    for tid, name in team_names.items():
        t = totals.get(tid)
        if not t:
            continue
        fga, fta = _num(t.get('avgFieldGoalsAttempted')), _num(t.get('avgFreeThrowsAttempted'))
        orb, tov = _num(t.get('avgOffensiveRebounds')), _num(t.get('avgTurnovers'))
        pts      = _num(t.get('avgPoints'))
        poss     = fga + 0.44 * fta - orb + tov          # estimated possessions per game
        if poss <= 0:
            continue
        pa, ga = allowed.get(tid, (0.0, 0))
        team_rows.append([tid, name, int(_num(t.get('gamesPlayed'))), round(poss, 2),
                          round(100 * pts / poss, 2), round(100 * pa / poss, 2) if pa else 0])
        if pa:
            opp_rows.append([tid, name, round(pa, 2)])
    write_table('raw_team_stats.json', ['TEAM_ID', 'TEAM_NAME', 'GP', 'PACE', 'OFF_RATING', 'DEF_RATING'],
                team_rows, 'team_stats')
    write_table('raw_opp_stats.json', ['TEAM_ID', 'TEAM_NAME', 'OPP_PTS'], opp_rows, 'opp_stats')

def fetch_espn_players(team_names, totals):
    """
    Season per-game averages for every qualified player (one call). Also derives usage,
    rebound and assist rates from the player's and team's per-game totals, since ESPN does
    not publish them. Returns [{id, name, team, ...}] for the recent-form step.
    """
    url = (f'{ESPN_COMMON}/statistics/byathlete?region=us&lang=en&contentorigin=espn'
           f'&isqualified=false&page=1&limit=500&sort=offensive.avgPoints%3Adesc'
           f'&season={ESPN_SEASON}&seasontype=2')
    d = fetch_json(url, ESPN_HEADERS, 'espn_players') or {}
    names_by_cat = {c.get('name'): c.get('names', []) for c in d.get('categories', [])}
    athletes = d.get('athletes', [])

    base, adv, players, seen_ids = [], [], [], set()
    for a in athletes:
        ath = a.get('athlete') or {}
        pid = str(ath.get('id', ''))
        if not pid or pid in seen_ids:
            continue
        seen_ids.add(pid)

        v = {}
        for c in a.get('categories', []):
            arr = c.get('totals') or c.get('values') or c.get('stats') or []
            for n, val in zip(names_by_cat.get(c.get('name'), []), arr):
                v[n] = val

        teams = ath.get('teams') or []
        tid   = str(teams[0].get('id')) if teams else ''
        tname = team_names.get(tid) or (teams[0].get('displayName') if teams else '')

        gp   = int(_num(v.get('gamesPlayed')))
        mins = _num(v.get('avgMinutes'))
        pts, reb, ast = _num(v.get('avgPoints')), _num(v.get('avgRebounds')), _num(v.get('avgAssists'))
        fgm, fga = _num(v.get('avgFieldGoalsMade')), _num(v.get('avgFieldGoalsAttempted'))
        fta, tov = _num(v.get('avgFreeThrowsAttempted')), _num(v.get('avgTurnovers'))
        f3m, f3a = _num(v.get('avgThreePointFieldGoalsMade')), _num(v.get('avgThreePointFieldGoalsAttempted'))
        if not name_ok(ath, tname):
            continue

        t = totals.get(tid, {})
        t_fga, t_fta, t_tov = (_num(t.get('avgFieldGoalsAttempted')), _num(t.get('avgFreeThrowsAttempted')),
                               _num(t.get('avgTurnovers')))
        t_fgm, t_reb = _num(t.get('avgFieldGoalsMade')), _num(t.get('avgRebounds'))
        usg = reb_pct = ast_pct = 0.0
        if mins > 0 and t:
            den = t_fga + 0.44 * t_fta + t_tov
            if den > 0:
                usg = (fga + 0.44 * fta + tov) * 48 / (mins * den)
            if t_reb > 0:
                reb_pct = reb * 48 / (mins * 2 * t_reb)        # assumes opponent rebounds ~ team rebounds
            den = (mins / 48) * t_fgm - fgm
            if den > 0:
                ast_pct = ast / den
        clamp = lambda x: round(max(0.0, min(1.0, x)), 4)

        name = ath.get('displayName', '')
        base.append([pid, name, tname, gp, mins, pts, reb, ast, f3m, f3a, round(f3m / f3a, 4) if f3a else 0])
        adv.append([pid, name, tname, clamp(usg), clamp(reb_pct), clamp(ast_pct)])
        players.append({'id': pid, 'name': name})

    if athletes and not base:
        sample = (athletes[0].get('categories') or [{}])[0]
        print(f'[fetch] WARNING players present but no stats parsed; first category keys: {list(sample.keys())}',
              file=sys.stderr)
    write_table('raw_player_stats.json',
                ['PLAYER_ID', 'PLAYER_NAME', 'TEAM_NAME', 'GP', 'MIN', 'PTS', 'REB', 'AST', 'FG3M', 'FG3A', 'FG3_PCT'],
                base, 'player_stats')
    write_table('raw_advanced_stats.json',
                ['PLAYER_ID', 'PLAYER_NAME', 'TEAM_NAME', 'USG_PCT', 'REB_PCT', 'AST_PCT'], adv, 'advanced_stats')
    return players

def name_ok(ath, tname):
    """Skip athletes with no name or no team (cannot be placed on tonight's slate)."""
    return bool(ath.get('displayName')) and bool(tname)

def props_player_names():
    """Normalized names of every player with a prop line today."""
    try:
        with open(os.path.join(OUTDIR, 'raw_props.json')) as f:
            props = json.load(f)
    except Exception:
        return set()
    out = set()
    for entry in props or []:
        data = entry.get('data') or {}
        for bk in data.get('bookmakers', []):
            for mk in bk.get('markets', []):
                for o in mk.get('outcomes', []):
                    n, desc = o.get('name', ''), o.get('description', '')
                    who = desc if n in ('Over', 'Under') else n
                    if who:
                        out.add(_norm_name(who))
    return out

def _gamelog(pid):
    """Newest-first list of {min, pts, reb, ast, fg3m} for this season's regular-season games."""
    d = fetch_json(f'{ESPN_COMMON}/athletes/{pid}/gamelog?region=us&lang=en&contentorigin=espn'
                   f'&season={ESPN_SEASON}', ESPN_HEADERS, f'gamelog/{pid}') or {}
    idx = {n: i for i, n in enumerate(d.get('names', []))}
    need = ('minutes', 'points', 'totalRebounds', 'assists', 'threePointFieldGoalsMade-threePointFieldGoalsAttempted')
    if any(k not in idx for k in need):
        return []
    events = []
    for st in d.get('seasonTypes', []):
        if 'regular' in (st.get('displayName') or '').lower():
            for cat in st.get('categories', []):
                events.extend(cat.get('events', []))
    meta = d.get('events') or {}
    events.sort(key=lambda e: ((meta.get(str(e.get('eventId'))) or {}).get('gameDate') or '',
                               int(_num(e.get('eventId')))), reverse=True)
    games = []
    for e in events:
        s = e.get('stats') or []
        try:
            mins = _num(s[idx['minutes']])
            if mins <= 0:
                continue                                    # DNP
            games.append({'pts': _num(s[idx['points']]), 'reb': _num(s[idx['totalRebounds']]),
                          'ast': _num(s[idx['assists']]),
                          'fg3m': _num(str(s[idx['threePointFieldGoalsMade-threePointFieldGoalsAttempted']]).split('-')[0])})
        except IndexError:
            continue
    return games

def fetch_recent_form(players):
    """L5 / L10 averages from game logs, only for players that have a prop line today."""
    wanted = props_player_names()
    targets = [p for p in players if _norm_name(p['name']) in wanted][:MAX_GAMELOGS]
    print(f'[fetch] game logs: {len(targets)} players with props (of {len(wanted)} prop names)')
    logs = _pmap(lambda p: (p, _gamelog(p['id'])), targets)
    headers = ['PLAYER_ID', 'PLAYER_NAME', 'GP', 'PTS', 'REB', 'AST', 'FG3M']
    for n, label in ((5, 'L5'), (10, 'L10')):
        rows = []
        for p, games in logs:
            w = games[:n]
            if not w:
                continue
            avg = lambda k: round(sum(g[k] for g in w) / len(w), 2)
            rows.append([p['id'], p['name'], len(w), avg('pts'), avg('reb'), avg('ast'), avg('fg3m')])
        write_table(f'raw_player_stats_{label}.json', headers, rows, f'player_stats_{label}')

# ── main ──────────────────────────────────────────────────────────────────────
if __name__ == '__main__':
    print(f'[fetch] slate date: {TODAY_ET}  season: {CURRENT_SEASON} (ESPN season={ESPN_SEASON})')
    print('[fetch] fetching games + odds...')
    fetch_games_and_odds()
    print('[fetch] fetching props...')
    fetch_props()
    print('[fetch] fetching ESPN teams...')
    team_names = fetch_espn_teams()
    print('[fetch] fetching ESPN team stats...')
    totals = fetch_espn_team_totals(team_names)
    print('[fetch] fetching points allowed (scoreboard)...')
    allowed = fetch_espn_points_allowed()
    build_team_tables(team_names, totals, allowed)
    print('[fetch] fetching ESPN player stats...')
    players = fetch_espn_players(team_names, totals)
    print('[fetch] fetching recent form (game logs)...')
    fetch_recent_form(players)
    print('[fetch] done.')
