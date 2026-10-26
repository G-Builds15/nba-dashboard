#!/usr/bin/env python3
"""
slate_builder.py
Grades props and game leans using NBA Stats API data.
Injects team colors from TEAM_COLORS lookup.
Writes slate_data.js for the dashboard to render.
"""

import argparse
import json
import os
import sys
import unicodedata
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
def _season_label(dt):
    start = dt.year if dt.month >= 10 else dt.year - 1
    return f'{start}-{(start + 1) % 100:02d}'

CURRENT_SEASON_LABEL = _season_label(datetime.now(ET))
TODAY_ET = datetime.now(ET).strftime('%Y-%m-%d')

# ── team colors (primary, secondary) ─────────────────────────────────────────
TEAM_COLORS = {
    'Atlanta Hawks':            {'primary': '#E03A3E', 'secondary': '#C1D32F', 'abbr': 'ATL', 'full': 'Atlanta Hawks'},
    'Boston Celtics':           {'primary': '#007A33', 'secondary': '#BA9653', 'abbr': 'BOS', 'full': 'Boston Celtics'},
    'Brooklyn Nets':            {'primary': '#000000', 'secondary': '#FFFFFF', 'abbr': 'BKN', 'full': 'Brooklyn Nets'},
    'Charlotte Hornets':        {'primary': '#1D1160', 'secondary': '#00788C', 'abbr': 'CHA', 'full': 'Charlotte Hornets'},
    'Chicago Bulls':            {'primary': '#CE1141', 'secondary': '#000000', 'abbr': 'CHI', 'full': 'Chicago Bulls'},
    'Cleveland Cavaliers':      {'primary': '#860038', 'secondary': '#FDBB30', 'abbr': 'CLE', 'full': 'Cleveland Cavaliers'},
    'Dallas Mavericks':         {'primary': '#00538C', 'secondary': '#002B5E', 'abbr': 'DAL', 'full': 'Dallas Mavericks'},
    'Denver Nuggets':           {'primary': '#0E2240', 'secondary': '#FEC524', 'abbr': 'DEN', 'full': 'Denver Nuggets'},
    'Detroit Pistons':          {'primary': '#C8102E', 'secondary': '#006BB6', 'abbr': 'DET', 'full': 'Detroit Pistons'},
    'Golden State Warriors':    {'primary': '#1D428A', 'secondary': '#FFC72C', 'abbr': 'GSW', 'full': 'Golden State Warriors'},
    'Houston Rockets':          {'primary': '#CE1141', 'secondary': '#000000', 'abbr': 'HOU', 'full': 'Houston Rockets'},
    'Indiana Pacers':           {'primary': '#002D62', 'secondary': '#FDBB30', 'abbr': 'IND', 'full': 'Indiana Pacers'},
    'LA Clippers':              {'primary': '#C8102E', 'secondary': '#1D428A', 'abbr': 'LAC', 'full': 'LA Clippers'},
    'Los Angeles Lakers':       {'primary': '#552583', 'secondary': '#FDB927', 'abbr': 'LAL', 'full': 'Los Angeles Lakers'},
    'Memphis Grizzlies':        {'primary': '#5D76A9', 'secondary': '#12173F', 'abbr': 'MEM', 'full': 'Memphis Grizzlies'},
    'Miami Heat':               {'primary': '#98002E', 'secondary': '#F9A01B', 'abbr': 'MIA', 'full': 'Miami Heat'},
    'Milwaukee Bucks':          {'primary': '#00471B', 'secondary': '#EEE1C6', 'abbr': 'MIL', 'full': 'Milwaukee Bucks'},
    'Minnesota Timberwolves':   {'primary': '#0C2340', 'secondary': '#236192', 'abbr': 'MIN', 'full': 'Minnesota Timberwolves'},
    'New Orleans Pelicans':     {'primary': '#0C2340', 'secondary': '#C8102E', 'abbr': 'NOP', 'full': 'New Orleans Pelicans'},
    'New York Knicks':          {'primary': '#006BB6', 'secondary': '#F58426', 'abbr': 'NYK', 'full': 'New York Knicks'},
    'Oklahoma City Thunder':    {'primary': '#007AC1', 'secondary': '#EF3B24', 'abbr': 'OKC', 'full': 'Oklahoma City Thunder'},
    'Orlando Magic':            {'primary': '#0077C0', 'secondary': '#C4CED4', 'abbr': 'ORL', 'full': 'Orlando Magic'},
    'Philadelphia 76ers':       {'primary': '#006BB6', 'secondary': '#ED174C', 'abbr': 'PHI', 'full': 'Philadelphia 76ers'},
    'Phoenix Suns':             {'primary': '#1D1160', 'secondary': '#E56020', 'abbr': 'PHX', 'full': 'Phoenix Suns'},
    'Portland Trail Blazers':   {'primary': '#E03A3E', 'secondary': '#000000', 'abbr': 'POR', 'full': 'Portland Trail Blazers'},
    'Sacramento Kings':         {'primary': '#5A2D81', 'secondary': '#63727A', 'abbr': 'SAC', 'full': 'Sacramento Kings'},
    'San Antonio Spurs':        {'primary': '#C4CED4', 'secondary': '#000000', 'abbr': 'SAS', 'full': 'San Antonio Spurs'},
    'Toronto Raptors':          {'primary': '#CE1141', 'secondary': '#000000', 'abbr': 'TOR', 'full': 'Toronto Raptors'},
    'Utah Jazz':                {'primary': '#002B5C', 'secondary': '#00471B', 'abbr': 'UTA', 'full': 'Utah Jazz'},
    'Washington Wizards':       {'primary': '#002B5C', 'secondary': '#E31837', 'abbr': 'WAS', 'full': 'Washington Wizards'},
}

def normalize(s):
    """Unicode normalize and lowercase for fuzzy name matching."""
    return unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower().strip()

_SUFFIXES = {'jr', 'sr', 'ii', 'iii', 'iv', 'v'}

def normalize_player(name):
    """normalize() plus punctuation and generational-suffix stripping, so 'P.J. Washington' / 'Jaren Jackson Jr.'
    match across The Odds API and the NBA Stats API."""
    n = normalize(name).replace('.', '').replace("'", '').replace(',', '').replace('-', ' ')
    parts = [p for p in n.split() if p]
    while parts and parts[-1] in _SUFFIXES:
        parts.pop()
    return ' '.join(parts)

# Build reverse lookup: abbreviation → team info
ABBR_TO_TEAM = {v['abbr']: v for v in TEAM_COLORS.values()}
# Build name → team info (normalized)
NAME_TO_TEAM = {normalize(k): v for k, v in TEAM_COLORS.items()}

def load_json(filename):
    path = os.path.join(OUTDIR, filename)
    if not os.path.exists(path):
        print(f'[slate] missing: {path}', file=sys.stderr)
        return None
    with open(path) as f:
        try:
            return json.load(f)
        except Exception as e:
            print(f'[slate] JSON error {filename}: {e}', file=sys.stderr)
            return None

def write_js(data):
    path = os.path.join(OUTDIR, 'slate_data.js')
    with open(path, 'w') as f:
        f.write('// Auto-generated by slate_builder.py — do not edit manually\n')
        f.write('const SLATE_DATA = ')
        json.dump(data, f, indent=2)
        f.write(';\n')
    print(f'[slate] wrote {path}')

# ── NBA Stats API data parsers ────────────────────────────────────────────────
def parse_nba_stats(raw):
    """Parse NBA Stats API resultSet format into list of dicts."""
    if not raw:
        return []
    result_sets = raw.get('resultSets', [])
    for rs in result_sets:
        headers = rs.get('headers', [])
        rows    = rs.get('rowSet', [])
        return [dict(zip(headers, row)) for row in rows]
    return []

def build_player_stat_lookup(base_stats, adv_stats, l10_stats=None, l5_stats=None):
    """
    Build player lookup keyed by normalized name.
    Merges base, advanced, L10, and L5 stats.
    Blended averages: season 60% / L10 25% / L5 15%
    Falls back gracefully when recent data is sparse (GP < 3).
    """
    SEASON_W = 0.60
    L10_W    = 0.25
    L5_W     = 0.15
    MIN_GP_RECENT = 3  # minimum games for recent split to count

    def blend(season_val, l10_val, l10_gp, l5_val, l5_gp):
        """Weighted blend; drops recent splits if too few games."""
        use_l10 = l10_val is not None and (l10_gp or 0) >= MIN_GP_RECENT
        use_l5  = l5_val  is not None and (l5_gp  or 0) >= MIN_GP_RECENT
        if use_l10 and use_l5:
            total_w = SEASON_W + L10_W + L5_W
            return (season_val * SEASON_W + l10_val * L10_W + l5_val * L5_W) / total_w
        elif use_l10:
            total_w = SEASON_W + L10_W
            return (season_val * SEASON_W + l10_val * L10_W) / total_w
        else:
            return season_val

    # Index recent splits by normalized name
    l10_idx = {}
    for row in (l10_stats or []):
        k = normalize_player(row.get('PLAYER_NAME', ''))
        l10_idx[k] = row

    l5_idx = {}
    for row in (l5_stats or []):
        k = normalize_player(row.get('PLAYER_NAME', ''))
        l5_idx[k] = row

    lookup = {}
    for row in base_stats:
        name = row.get('PLAYER_NAME', '')
        key  = normalize_player(name)
        l10  = l10_idx.get(key, {})
        l5   = l5_idx.get(key, {})

        def b(field):
            sv  = row.get(field, 0) or 0
            l10v = l10.get(field)
            l5v  = l5.get(field)
            return blend(sv, l10v, l10.get('GP'), l5v, l5.get('GP'))

        lookup[key] = {
            'player_name':    name,
            'team_abbr':      row.get('TEAM_ABBREVIATION', ''),
            'gp':             row.get('GP', 0) or 0,
            # blended per-game averages
            'pts':            b('PTS'),
            'reb':            b('REB'),
            'ast':            b('AST'),
            'fg3m':           b('FG3M'),
            'fg3a':           b('FG3A'),
            'fg3_pct':        b('FG3_PCT'),
            # raw season values for rate stats (not averaged)
            'pts_season':     row.get('PTS', 0) or 0,
            'pts_l10':        l10.get('PTS'),
            'pts_l5':         l5.get('PTS'),
            'reb_l10':        l10.get('REB'),
            'reb_l5':         l5.get('REB'),
            'ast_l10':        l10.get('AST'),
            'ast_l5':         l5.get('AST'),
            'fg3m_l10':       l10.get('FG3M'),
            'fg3m_l5':        l5.get('FG3M'),
        }

    for row in adv_stats:
        name = row.get('PLAYER_NAME', '')
        key  = normalize_player(name)
        if key in lookup:
            lookup[key]['usg_pct'] = row.get('USG_PCT', 0) or 0
            lookup[key]['reb_pct'] = row.get('REB_PCT', 0) or 0
            lookup[key]['ast_pct'] = row.get('AST_PCT', 0) or 0
        else:
            lookup[key] = {
                'player_name': name,
                'team_abbr':   row.get('TEAM_ABBREVIATION', ''),
                'usg_pct':     row.get('USG_PCT', 0) or 0,
                'reb_pct':     row.get('REB_PCT', 0) or 0,
                'ast_pct':     row.get('AST_PCT', 0) or 0,
                'pts': 0, 'reb': 0, 'ast': 0, 'fg3m': 0, 'fg3a': 0, 'fg3_pct': 0, 'gp': 0,
            }
    return lookup

def _team_abbr(row):
    """leaguedashteamstats returns TEAM_ID / TEAM_NAME only, so derive the abbreviation from the name."""
    abbr = row.get('TEAM_ABBREVIATION')
    if abbr:
        return abbr
    name = row.get('TEAM_NAME', '')
    info = get_team_info(name) if name else None
    return info['abbr'] if info else ''

def build_team_stat_lookup(team_stats, opp_stats):
    """Build team lookup keyed by team abbreviation."""
    lookup = {}
    for row in team_stats:
        abbr = _team_abbr(row)
        if not abbr:
            continue
        lookup[abbr] = {
            'pace':     row.get('PACE', 0) or 0,
            'off_rtg':  row.get('OFF_RATING', 0) or 0,
            'def_rtg':  row.get('DEF_RATING', 0) or 0,
        }
    for row in opp_stats:
        abbr = _team_abbr(row)
        if abbr in lookup:
            lookup[abbr]['opp_pts']  = row.get('OPP_PTS', 0) or 0
            lookup[abbr]['opp_reb']  = row.get('OPP_REB', 0) or 0
            lookup[abbr]['opp_ast']  = row.get('OPP_AST', 0) or 0
            lookup[abbr]['opp_fg3m'] = row.get('OPP_FG3M', 0) or 0
    return lookup

# ── grading logic ─────────────────────────────────────────────────────────────

MIN_GP_GRADE    = 3       # games played before a prop is graded (below this -> 'N/A')
LEAGUE_AVG_PACE = 99.2    # last-resort fallback only; the real value comes from team_stats

# (strong, moderate, poor) edge cut-offs per prop type, in stat units
EDGE_RULES = {'pts': (3, 1, -2), 'reb': (2, 0.5, -1.5), 'ast': (1.5, 0.5, -1),
              '3pm': (1, 0.3, -0.5), 'pra': (4, 1, -3)}

def league_avgs(team_stats):
    """League-wide means computed from today's team table (no hardcoded league constants)."""
    out = {}
    for key in ('pace', 'opp_pts', 'opp_reb', 'opp_ast', 'opp_fg3m'):
        vals = [t.get(key, 0) for t in team_stats.values() if t.get(key, 0)]
        out[key] = sum(vals) / len(vals) if vals else 0
    return out

def pace_factor(player_team_abbr, opp_abbr, team_stats, league_pace=0):
    """Tonight's expected pace relative to league average (>1.0 = more possessions)."""
    base = league_pace or LEAGUE_AVG_PACE
    pp = team_stats.get(player_team_abbr, {}).get('pace') or base
    op = team_stats.get(opp_abbr, {}).get('pace') or base
    return ((pp + op) / 2) / base

def _opp_signal(value, league_value):
    """+1 if the opponent allows clearly more than league average, -1 if clearly less, else 0."""
    if not value or not league_value:
        return 0
    if value > league_value * 1.03: return 1
    if value < league_value * 0.97: return -1
    return 0

def _trend_note(l5_val, l10_val, season_val):
    """Return a short trend string if recent form diverges meaningfully from season avg."""
    if not season_val:
        return ''
    if l5_val is not None:
        pct_diff = (l5_val - season_val) / season_val
        if pct_diff > 0.15:
            return f', 🔥 L5 {l5_val:.1f}'
        elif pct_diff < -0.15:
            return f', ❄️ L5 {l5_val:.1f}'
    if l10_val is not None:
        pct_diff = (l10_val - season_val) / season_val
        if pct_diff > 0.12:
            return f', ↑ L10 {l10_val:.1f}'
        elif pct_diff < -0.12:
            return f', ↓ L10 {l10_val:.1f}'
    return ''

def grade_prop(prop, player_stats, team_stats, league=None):
    """
    Grade a player prop A/B/C/D, or 'N/A' when there is not enough data.

    - Blended player average (season 60% / L10 25% / L5 15%), scaled to tonight's pace
    - Opponent defense vs league average, usage / rate stats, pace
    Contextual signals are multiplied by `sign` (+1 Over, -1 Under) so a fast game or a
    high-usage player helps an Over and hurts an Under. Only the statistical edge is
    already direction-aware.
    """
    league      = league or {}
    prop_type   = prop.get('prop_type', '')
    line        = prop.get('line')
    direction   = prop.get('direction', '')
    player_team = prop.get('team', '')
    opp_abbr    = prop.get('opp_abbr', '')

    if line is None or direction not in ('Over', 'Under') or prop_type not in EDGE_RULES:
        return 'N/A', ''
    pdata = player_stats.get(normalize_player(prop.get('player_name', '')))
    if not pdata or (pdata.get('gp') or 0) < MIN_GP_GRADE:
        return 'N/A', ''

    opp   = team_stats.get(opp_abbr, {})
    sign  = 1 if direction == 'Over' else -1
    pf    = pace_factor(player_team, opp_abbr, team_stats, league.get('pace', 0))
    pace_pt = (1 if pf > 1.03 else -1 if pf < 0.97 else 0) * sign

    if prop_type == 'pra':
        raw = pdata.get('pts', 0) + pdata.get('reb', 0) + pdata.get('ast', 0)
    else:
        raw = pdata.get({'pts': 'pts', 'reb': 'reb', 'ast': 'ast', '3pm': 'fg3m'}[prop_type], 0)
    if not raw:
        return 'N/A', ''
    avg  = raw * pf
    edge = avg - line if direction == 'Over' else line - avg
    hi, mid, lo = EDGE_RULES[prop_type]
    score = 2 if edge > hi else 1 if edge > mid else -1 if edge < lo else 0
    score += pace_pt

    if prop_type == 'pts':
        usg = pdata.get('usg_pct', 0)
        if usg and usg > 0.28: score += sign
        score += _opp_signal(opp.get('opp_pts'), league.get('opp_pts')) * sign
        trend = _trend_note(pdata.get('pts_l5'), pdata.get('pts_l10'), raw)
        rationale = f"Blended avg {avg:.1f} pts (×{pf:.2f} pace), USG {usg*100:.1f}%{trend}"
    elif prop_type == 'reb':
        reb_pct = pdata.get('reb_pct', 0)
        if reb_pct and reb_pct > 0.15: score += sign
        score += _opp_signal(opp.get('opp_reb'), league.get('opp_reb')) * sign
        trend = _trend_note(pdata.get('reb_l5'), pdata.get('reb_l10'), raw)
        rationale = f"Blended avg {avg:.1f} reb (×{pf:.2f} pace), REB% {reb_pct*100:.1f}%{trend}"
    elif prop_type == 'ast':
        ast_pct = pdata.get('ast_pct', 0)
        if ast_pct and ast_pct > 0.25: score += sign
        score += _opp_signal(opp.get('opp_ast'), league.get('opp_ast')) * sign
        trend = _trend_note(pdata.get('ast_l5'), pdata.get('ast_l10'), raw)
        rationale = f"Blended avg {avg:.1f} ast (×{pf:.2f} pace), AST% {ast_pct*100:.1f}%{trend}"
    elif prop_type == '3pm':
        pct, att = pdata.get('fg3_pct', 0), pdata.get('fg3a', 0)
        if pct and pct > 0.38: score += sign
        if att and att > 8:    score += sign
        score += _opp_signal(opp.get('opp_fg3m'), league.get('opp_fg3m')) * sign
        trend = _trend_note(pdata.get('fg3m_l5'), pdata.get('fg3m_l10'), raw)
        rationale = f"Blended avg {avg:.1f} 3PM (×{pf:.2f} pace), {pct*100:.1f}% on {att:.1f} att{trend}"
    else:  # pra
        rationale = f"Blended PRA avg {avg:.1f} (×{pf:.2f} pace)"

    if score >= 3:   return 'A', rationale
    elif score == 2: return 'B', rationale
    elif score == 1: return 'C', rationale
    else:            return 'D', rationale

def grade_spread(home_abbr, away_abbr, spread_home, team_stats):
    """Simple spread grade based on home/away net rating differential."""
    home = team_stats.get(home_abbr, {})
    away = team_stats.get(away_abbr, {})
    home_net = home.get('off_rtg', 0) - home.get('def_rtg', 0)
    away_net = away.get('off_rtg', 0) - away.get('def_rtg', 0)
    if home_net == 0 and away_net == 0:
        return 'N/A', None
    net_diff = home_net - away_net
    # Positive spread_home means home is underdog
    if spread_home is not None and spread_home < 0:
        # Home favored
        if net_diff > 6: return 'A', home_abbr
        elif net_diff > 2: return 'B', home_abbr
        elif net_diff > -1: return 'C', home_abbr
        else: return 'D', home_abbr
    else:
        # Away favored or pick'em
        if net_diff < -6: return 'A', away_abbr
        elif net_diff < -2: return 'B', away_abbr
        elif net_diff < 1: return 'C', home_abbr
        else: return 'D', home_abbr

def grade_total(home_abbr, away_abbr, total_line, team_stats):
    """Grade total based on combined team pace and offensive ratings."""
    home = team_stats.get(home_abbr, {})
    away = team_stats.get(away_abbr, {})
    combined_pace = (home.get('pace', 0) + away.get('pace', 0)) / 2
    combined_off = (home.get('off_rtg', 0) + away.get('off_rtg', 0)) / 2
    if combined_pace == 0 or total_line is None:
        return 'N/A', None
    # Rough expected total from pace + off rating
    expected = combined_pace * (combined_off / 100) * 2
    edge = expected - total_line
    if edge > 8: return 'A', 'Over'
    elif edge > 3: return 'B', 'Over'
    elif edge < -8: return 'A', 'Under'
    elif edge < -3: return 'B', 'Under'
    else: return 'C', 'Over' if edge >= 0 else 'Under'

def get_team_info(team_name):
    """Fuzzy match team name to TEAM_COLORS."""
    key = normalize(team_name)
    # Exact match
    if key in NAME_TO_TEAM:
        return NAME_TO_TEAM[key]
    # Partial match on last word (city names differ)
    last_word = key.split()[-1] if key else ''
    for full_key, info in NAME_TO_TEAM.items():
        if last_word and last_word in full_key:
            return info
    return {'primary': '#444444', 'secondary': '#666666', 'abbr': team_name[:3].upper(), 'full': team_name}

# ── main build ────────────────────────────────────────────────────────────────
def build():
    odds_data    = load_json('odds_data.json') or {}
    raw_base     = load_json('raw_player_stats.json') or {}
    raw_adv      = load_json('raw_advanced_stats.json') or {}
    raw_team     = load_json('raw_team_stats.json') or {}
    raw_opp      = load_json('raw_opp_stats.json') or {}
    raw_l10      = load_json('raw_player_stats_L10.json') or {}
    raw_l5       = load_json('raw_player_stats_L5.json') or {}
    tracker_data = load_json('tracker.json')

    base_stats = parse_nba_stats(raw_base)
    adv_stats  = parse_nba_stats(raw_adv)
    team_rows  = parse_nba_stats(raw_team)
    opp_rows   = parse_nba_stats(raw_opp)
    l10_stats  = parse_nba_stats(raw_l10)
    l5_stats   = parse_nba_stats(raw_l5)

    player_stats = build_player_stat_lookup(base_stats, adv_stats, l10_stats, l5_stats)
    team_stats   = build_team_stat_lookup(team_rows, opp_rows)
    league       = league_avgs(team_stats)

    if not player_stats:
        print('[slate] WARNING: no player stats parsed - every prop will be N/A', file=sys.stderr)
    if not team_stats:
        print('[slate] WARNING: no team stats parsed - leans will be N/A, pace/defense signals off', file=sys.stderr)
    unmatched = []   # prop players we could not place on a team

    games_raw       = odds_data.get('games', [])
    props_by_event  = odds_data.get('props_by_event', {})

    output_games = []
    best_bets_count = 0

    for g in games_raw:
        home_name   = g.get('home_team', '')
        away_name   = g.get('away_team', '')
        home_info   = get_team_info(home_name)
        away_info   = get_team_info(away_name)
        home_abbr   = home_info['abbr']
        away_abbr   = away_info['abbr']

        # Grade spread
        spread_grade, spread_lean_team = grade_spread(
            home_abbr, away_abbr, g.get('spread_home'), team_stats)
        if spread_lean_team == home_abbr:
            spread_line_val = g.get('spread_home')
            spread_odds_val = g.get('odds_spread_home')
            lean_spread_str = f"{home_abbr} {spread_line_val:+.1f}" if spread_line_val is not None else home_abbr
        else:
            spread_line_val = g.get('spread_away')
            spread_odds_val = g.get('odds_spread_away')
            lean_spread_str = f"{away_abbr} {spread_line_val:+.1f}" if spread_line_val is not None else away_abbr

        # Grade total
        total_grade, total_direction = grade_total(
            home_abbr, away_abbr, g.get('total_line'), team_stats)
        total_line_val = g.get('total_line')
        lean_total_str = f"{total_direction} {total_line_val}" if total_line_val else ''
        total_odds_val = g.get('odds_over') if total_direction == 'Over' else g.get('odds_under')

        # Moneyline lean — favor whichever side we graded spread
        if spread_lean_team == home_abbr:
            lean_ml_str  = f"{home_abbr}"
            ml_odds_val  = g.get('odds_ml_home')
            grade_ml     = spread_grade
        else:
            lean_ml_str  = f"{away_abbr}"
            ml_odds_val  = g.get('odds_ml_away')
            grade_ml     = spread_grade

        # No grade means no analysis: never show a lean (or "None 219.5") without a basis
        if spread_grade == 'N/A':
            lean_spread_str, spread_odds_val = '', None
        if total_grade == 'N/A' or not total_direction:
            lean_total_str, total_odds_val = '', None
        if grade_ml == 'N/A':
            lean_ml_str, ml_odds_val = '', None

        best_bet_spread = spread_grade in ('A', 'B')
        best_bet_total  = total_grade in ('A', 'B')

        # Grade props
        event_id = g.get('event_id', '')
        raw_props = props_by_event.get(event_id, [])
        graded_props = []
        for p in raw_props:
            # Determine which team this player is on
            pdata = player_stats.get(normalize_player(p.get('player_name', '')))
            player_team = (pdata or {}).get('team_abbr', '')
            if player_team not in (home_abbr, away_abbr):
                # Not found in the NBA feed (name mismatch, rookie, traded) - do not guess a team
                unmatched.append(p.get('player_name', '?'))
                continue
            opp = away_abbr if player_team == home_abbr else home_abbr

            p_with_opp = {**p, 'opp_abbr': opp, 'team': player_team}
            grade, rationale = grade_prop(p_with_opp, player_stats, team_stats, league)

            is_best = grade in ('A', 'B')
            if is_best:
                best_bets_count += 1

            graded_props.append({
                **p,
                'team':      player_team,
                'grade':     grade,
                'rationale': rationale,
                'best_bet':  is_best,
                'opp_abbr':  opp,
            })

        output_games.append({
            'event_id':             event_id,
            'home_team':            home_name,
            'away_team':            away_name,
            'home_abbr':            home_abbr,
            'away_abbr':            away_abbr,
            'home_full':            home_info['full'],
            'away_full':            away_info['full'],
            'home_color_primary':   home_info['primary'],
            'home_color_secondary': home_info['secondary'],
            'away_color_primary':   away_info['primary'],
            'away_color_secondary': away_info['secondary'],
            'game_time':            g.get('game_time', ''),
            'venue':                '',
            'lean_spread':          lean_spread_str,
            'odds_spread':          spread_odds_val,
            'grade_spread':         spread_grade,
            'best_bet_spread':      best_bet_spread,
            'lean_total':           lean_total_str,
            'odds_total':           total_odds_val,
            'grade_total':          total_grade,
            'best_bet_total':       best_bet_total,
            'lean_ml':              lean_ml_str,
            'odds_ml':              ml_odds_val,
            'grade_ml':             grade_ml,
            'props':                graded_props,
        })

    slate = {
        'slate_date':    TODAY_ET,
        'generated_at':  datetime.now(ET).isoformat(),
        'games':         output_games,
        'tracker':       tracker_data,
        'data_status': {
            'season':            CURRENT_SEASON_LABEL,
            'player_rows':       len(player_stats),
            'team_rows':         len(team_stats),
            'props_unmatched':   len(unmatched),
        },
    }
    if unmatched:
        names = sorted(set(unmatched))
        print(f'[slate] {len(unmatched)} props skipped, player not found in NBA feed: {names[:15]}'
              f'{" ..." if len(names) > 15 else ""}', file=sys.stderr)
    write_js(slate)
    print(f'[slate] {len(output_games)} games, {best_bets_count} best bets')

if __name__ == '__main__':
    build()
