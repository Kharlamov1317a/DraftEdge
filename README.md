# DraftEdge Fantasy Draft Assistant — v3.1

https://share.streamlit.io/

## v3.1 hotfix

- Fixes nflverse loading failure: `The column label 'join_key' is not unique.`
- The historical-stat merge now includes the `join_key` merge column exactly once.
- Existing v3 functionality is otherwise unchanged.

DraftEdge is a Streamlit fantasy-football draft assistant designed for redraft leagues and responsive use on desktop and mobile browsers. Version 3 includes automated current-data ingest, Superflex/TE-premium valuation, injury/depth-chart context, weighted projection blending, Monte Carlo "take now vs wait" estimates, and read-only Sleeper live draft synchronization.


## v3: iPhone + desktop deployment

Version 3 keeps the same draft engine and adds a responsive mobile layout plus deployment/launcher files so the same app can be opened from an iPhone, Mac, Windows PC, or other computer.

**Recommended:** deploy the folder to Streamlit Community Cloud and use the resulting `*.streamlit.app` URL on every device. For same-Wi-Fi use without cloud hosting, run `run_draftedge_network.sh` on macOS/Linux or `run_draftedge_windows.bat` on Windows and open the computer's LAN URL from the iPhone.

See **`DEPLOY_MOBILE.md`** for the complete setup.

Included deployment files:

- `.streamlit/config.toml` — headless/network-ready Streamlit configuration
- `run_draftedge_network.sh` — Mac/Linux LAN launcher that prints the iPhone URL
- `run_draftedge_windows.bat` — Windows LAN launcher
- `start_cloud.sh` — generic cloud start command with `$PORT` support
- `Dockerfile` — container deployment
- responsive CSS for touch controls, narrow screens, scrollable tabs, and large draft tables

For Streamlit Community Cloud, select **Python 3.12** when deploying to match the provided Docker/runtime target and maximize dependency compatibility.

## Core feature set

- live snake-draft board with manual pick entry and undo
- optional Sleeper draft synchronization
- automatic opponent-pick simulation for mock drafts
- dynamic overall and position rankings
- player tiers and fantasy role/archetype categories
- Value Over Replacement (VOR)
- roster-aware recommendations
- Standard, Half-PPR, PPR, custom PPR
- TE premium scoring
- Superflex roster valuation
- injury and practice-status context
- depth-chart order context
- ADP/ECR market signal
- multiple projection-source blending with user-controlled weights
- Monte Carlo next-pick availability and "take-now edge"
- save/load draft state
- ranking CSV export
- PFR/custom CSV import
- automatic nflverse data loader

## Quick start

### macOS / Linux

```bash
cd fantasy_draft_assistant_v3
./run_draftedge.sh
```

### Windows

Double-click:

```text
run_draftedge_windows.bat
```

### Manual install

```bash
python -m venv .venv
source .venv/bin/activate        # macOS/Linux
# .venv\Scripts\activate       # Windows PowerShell
pip install -r requirements.txt
streamlit run app.py
```

Streamlit normally opens the app at `http://localhost:8501`.

---

## Recommended 2026 setup

Open **Data Hub** and use:

- Draft season: `2026`
- Historical-stat season: `2025`

Press **Load nflverse player pool**.

The loader attempts to combine:

1. previous-season player production
2. current-season rosters
3. current injury/practice status
4. current depth charts
5. current fantasy ranking information exposed through nflverse

The exact availability of an individual nflverse dataset depends on its upstream update schedule. DraftEdge shows which component datasets loaded and displays non-fatal loader errors in the UI.

### Why historical 2025 + current 2026?

Before the 2026 regular season begins, there is little or no meaningful 2026 regular-season production to use. The app therefore treats 2025 production as historical evidence and combines it with 2026 roster, injury, depth-chart and market information.

---

## Pro Football Reference data

PFR data remains **user-imported rather than automatically scraped**. Export/copy the table you want to use into a CSV and open **Data Hub → PFR / custom historical CSV**.

Recognized fields include common PFR-style names such as:

- `Player`
- `Tm`
- `FantPos`
- `G`
- `Tgt`
- `Rec`
- `FantPt`
- `PPR`

Repeated headings such as multiple `Yds` or `TD` columns should be renamed to explicit canonical fields before import:

```text
passing_yards
passing_td
rushing_attempts
rushing_yards
rushing_td
receiving_yards
receiving_td
```

---

## Projection blending

DraftEdge can blend multiple external projection files.

Each file should contain at least:

```text
player,projection
```

Recommended:

```text
player,position,projection,adp,ecr
```

Example:

```csv
player,position,projection,adp,ecr
Player One,RB,278.4,8.2,7.0
Player Two,WR,265.1,11.7,10.5
```

Upload several files at once and set a weight for each source. DraftEdge calculates a weighted mean for projections and, when present, ADP/ECR. The app can also include its historical baseline as another weighted source.

A source with weight `2.0` contributes twice as much as a source with weight `1.0`.

---

## Ranking model

The v3 base Draft Value score uses:

- projected fantasy scoring
- VOR
- historical usage
- ADP/ECR market information
- depth-chart order
- injury status

The live recommendation score then adds:

- unfilled starter requirements
- FLEX/SUPERFLEX roster construction
- positional scarcity
- probability of surviving to your next pick
- Monte Carlo urgency when available

The ranking model is intentionally transparent and heuristic. It is not a trained claim that one player has a precisely estimated probability of outperforming another.

---

## Superflex

Set **SUPERFLEX** to `1` (or more) in the sidebar.

This changes:

- QB replacement level
- QB positional scarcity
- roster-need multipliers
- opponent draft simulation
- Monte Carlo recommendations

In a normal 1-QB league, DraftEdge does not automatically treat quarterbacks as if they were Superflex assets.

---

## TE premium

Set **TE premium (extra PPR)** in the sidebar.

Example:

- normal receptions = `1.0` point
- TE premium = `0.5`

A TE reception is then worth `1.5` points while RB/WR receptions remain worth `1.0`.

The resulting scoring change is incorporated when DraftEdge derives projections from stat lines. If you upload an external point-projection total, DraftEdge treats that total as already expressed in your league's intended scoring format; use a TE-premium projection source when drafting a TE-premium league.

---

## Player role categories

DraftEdge uses production and usage to assign categories.

### QB

- Dual-Threat QB
- High-Volume Passer
- Pocket QB
- Streaming / Developmental QB

### RB

- Workhorse RB
- Receiving RB
- Goal-Line RB
- Early-Down / Committee RB
- Handcuff / Upside RB

### WR

- Alpha / Target-Hog WR
- Deep-Threat WR
- Red-Zone WR
- Possession WR
- Boom/Bust / Upside WR

### TE

- Elite Target TE
- High-Volume TE
- Red-Zone TE
- Streaming / Upside TE

---

## Monte Carlo: take now vs wait

When it is your pick, DraftEdge can automatically simulate the selections between your current pick and your next scheduled pick.

Opponent selections are probabilistic and use:

- current ADP
- DraftEdge board value
- inferred roster need
- position scarcity indirectly through player value and need

For the top candidates, the app reports:

- **MC next-pick availability** — fraction of simulated drafts in which the player survives
- **Wait value** — expected best option at your next pick if you pass
- **Take-now edge** — urgency advantage of selecting the candidate now rather than relying on the next-pick state
- **Common fallback** — player most often available as the best fallback when the candidate is gone

This is a decision-support model. It is not a calibrated market probability and does not know the individual preferences of the people in your real league.

---

## Sleeper live synchronization

Open **Sleeper Live** and enter the numeric Sleeper draft ID.

Optionally enter your Sleeper username. If the draft exposes the username's draft order, DraftEdge will attempt to infer your draft slot.

Press:

**Connect + apply Sleeper settings**

DraftEdge will attempt to:

1. read the draft
2. read its league scoring settings when a league is associated
3. apply roster slot settings
4. map active Sleeper player IDs to the DraftEdge player pool
5. import all completed picks

You can then enable **Auto-refresh picks**.

Sleeper's public API is read-only. DraftEdge does not make, queue, cancel or modify picks in Sleeper.

### Sleeper API behavior

The Sleeper player map is cached because it is much larger than the draft-pick endpoint and Sleeper explicitly recommends fetching the complete player map sparingly. Live polling refreshes the draft picks separately.

---

## Live-draft workflow

1. Load 2026 data through nflverse and/or import your own historical data.
2. Blend one or more projection sources if available.
3. Configure scoring and roster settings, or connect a Sleeper draft.
4. Open **Draft Room**.
5. When picks occur, either:
   - let Sleeper sync them, or
   - enter them manually.
6. On your turn, compare:
   - Best Pick
   - Best Value
   - Safest
   - Upside
   - Scarcity
   - Take Now
7. Use **Next-pick avail.** and **Take-now edge** to decide whether a player can reasonably be deferred.
8. Save the draft state periodically from **League & Draft**.

---

## Current limitations

- Sleeper sync is read-only.
- ESPN/Yahoo live draft synchronization is not included.
- Traded Sleeper draft picks can create more complicated future-slot ownership than the app's basic snake schedule assumes for recommendation timing.
- The Monte Carlo model infers opponent needs but does not learn your league-mates' historical drafting preferences.
- Injury/depth-chart data depend on the availability and update timing of nflverse/Sleeper upstream data.
- Historical production is not the same thing as a 2026 projection; external projection blending is recommended for serious drafts.
- No auction mode yet.
- No keeper/dynasty valuation yet.

---

## Data/API projects used

- nflverse: https://nflverse.nflverse.com/
- nflreadpy: https://github.com/nflverse/nflreadpy
- Sleeper API documentation: https://docs.sleeper.com/

Review upstream licenses/terms before redistributing datasets or deploying the app commercially.

## Files

```text
app.py                    Streamlit application
fantasy_engine.py         rankings, VOR, roles, recommendations, Monte Carlo
data_sources.py           nflverse ingest and projection blending
sleeper_client.py         Sleeper API client and pick synchronization
demo_data.py              deterministic fictional demo player pool
requirements.txt          Python dependencies
run_draftedge.sh          macOS/Linux launcher
run_draftedge_windows.bat Windows launcher
tests/test_engine.py      core regression tests
data/                      examples and column guidance
```
