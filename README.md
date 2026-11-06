# Court Report — NBA Dashboard

Automated NBA props and game-lean dashboard, rebuilt twice daily by GitHub Actions.

**Live:** https://g-builds15.github.io/nba-dashboard/nba_dashboard.html
**Tracker data:** https://g-builds15.github.io/nba-dashboard/tracker.json

## Pipeline (`.github/workflows/update.yml`)

1. `fetch_data.py`   – game lines + player props (The Odds API); player, team and recent-form stats (ESPN public endpoints; stats.nba.com blocks GitHub runners). Logs rows per table.
2. `odds_fetcher.py` – assembles raw odds into `odds_data.json`.
3. `slate_builder.py` – grades props and leans, applies team colors, writes `slate_data.js`.
4. `update_tracker.py` – appends today's A/B picks to `tracker.json` (results start as `Pending`) and refreshes the embedded tracker.
5. `build.py` – inlines `slate_data.js` into `nba_dashboard.html` between the `SLATE:START/END` markers (idempotent).

Raw API files are git-ignored; only `nba_dashboard.html`, `slate_data.js` and `tracker.json` are committed.

## Setup

1. Create the repo `G-Builds15/nba-dashboard` (public, empty) and push these files.
2. Settings → Secrets and variables → Actions → add `ODDS_API_KEY`.
3. Settings → Pages → Deploy from branch → `main` / `(root)`.
4. Actions → "NBA Dashboard Update" → Run workflow. Read the fetch step log (see below).

## First-run check (fetch step log)

Each NBA endpoint prints a line like `[fetch] OK team_stats: 30 rows; cols=[...]`.
- `WARNING EMPTY` on a stats line means ESPN returned nothing to the runner (the dashboard then shows a banner and hides player props).
- `team_stats` columns should include `TEAM_NAME`, `PACE`, `OFF_RATING`, `DEF_RATING`; `opp_stats` should include `OPP_PTS`, `OPP_REB`, `OPP_AST`, `OPP_FG3M`.

## Grading notes

- Prop average = season 60% / L10 25% / L5 15%, scaled to tonight's pace; opponent defense is compared with the league average computed from that day's team table.
- Contextual signals (pace, usage, opponent) help Overs and hurt Unders.
- Players with fewer than `MIN_GP_GRADE` (3) games are `N/A`. Players not found in the NBA feed are hidden and listed in the slate log.
- Results in `tracker.json` are graded manually (`result`: Win/Loss/Push, `pl`: units).

## Stats source notes
- Season stats come from ESPN's `byathlete` endpoint; recent form (L5/L10) from per-player game logs, fetched only for players with a prop today.
- ESPN does not publish pace, ratings or usage, so these are **estimated** from per-game box-score totals: possessions = FGA + 0.44*FTA - OREB + TO; usage, REB% and AST% from the player's and team's per-game totals; points allowed from completed scoreboard games.
- Opponent rebounds / assists / 3PM allowed are not available, so only the opponent *points* signal is used.
- With only a few games played, every average is noisy; props need 3+ games and recent splits need 3+ games.
- Injuries come from ESPN's injury report. An absent player's scoring is split: 35% picked up by the rotation, 25% net loss to the team, 40% absorbed by the bench (tunable constants at the top of the injuries block in slate_builder.py). Out/Doubtful players are not graded; Questionable players are capped at C.


## Projection model (props)
- **Minutes first**: expected stat = per-minute rate x projected minutes. Rates blend this season with last season
  (`raw_prior_players.json`, ESPN season-1) by games played, then lean slightly on the last 10 games. Minutes blend
  recent games, season and last season, then adjust for back-to-backs, blowout risk (large spreads trim starters'
  minutes) and the player's own injury status.
- **3PM** = attempts per minute x shrunk 3P% (league 36% anchor -> last season -> this season).
- The projected mean is then shrunk toward the mean the book's price implies (`MU_SHRINK_K`).

## Logging for review
Each tracker pick stores `ev`, `p` (model win probability at pick time), `open_odds`, and `close_odds`/`close_line`
(the last price seen before tip-off; snapshots happen on each full run). `python3 review.py` prints the record,
calibration by probability bucket, and closing-line value. Note: closing price is the last *snapshot*, not the
exact market close, because odds are only fetched on full runs.
