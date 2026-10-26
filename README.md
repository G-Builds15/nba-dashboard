# Court Report — NBA Dashboard

Automated NBA props and game-lean dashboard, rebuilt twice daily by GitHub Actions.

**Live:** https://g-builds15.github.io/nba-dashboard/nba_dashboard.html
**Tracker data:** https://g-builds15.github.io/nba-dashboard/tracker.json

## Pipeline (`.github/workflows/update.yml`)

1. `fetch_data.py`   – game lines + player props (The Odds API); player/team stats (NBA Stats API). Logs rows/columns per endpoint.
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
- `WARNING EMPTY` on the NBA lines means stats.nba.com returned nothing to the runner (the dashboard then shows a banner and hides player props).
- `team_stats` columns should include `TEAM_NAME`, `PACE`, `OFF_RATING`, `DEF_RATING`; `opp_stats` should include `OPP_PTS`, `OPP_REB`, `OPP_AST`, `OPP_FG3M`.

## Grading notes

- Prop average = season 60% / L10 25% / L5 15%, scaled to tonight's pace; opponent defense is compared with the league average computed from that day's team table.
- Contextual signals (pace, usage, opponent) help Overs and hurt Unders.
- Players with fewer than `MIN_GP_GRADE` (3) games are `N/A`. Players not found in the NBA feed are hidden and listed in the slate log.
- Results in `tracker.json` are graded manually (`result`: Win/Loss/Push, `pl`: units).
