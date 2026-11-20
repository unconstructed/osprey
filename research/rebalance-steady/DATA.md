# rebalance-steady: data coverage (counts only)

Written 2026-11-20 by `data-engineer` for part 1 (build and pre-register) of the `rebalance-steady` scouting study.
**This file holds only coverage counts and close dates.** No price, return or other price-based statistic was
computed or printed, and nothing closing after 2024-07-01 00:00 UTC (the test window) was requested.

- Snapshot: **`1746a21b75683e76`** (`data/catalog/SNAPSHOT.json`, created 2026-11-20T02:49:20Z).
- Loader: `lab.data.panel.load_panel(source, interval, last_close="2024-07-01")`. BTC and ETH bars come from the
  Nautilus catalog, restricted to the train and validate windows (`lab.config.in_window`, close-time rule).
  A close is kept only where **both** assets have a bar (an inner join; nothing filled). Every dropped close is
  listed in `attrs["alignment"]`.
- Instruments: KRAKEN = `BTC/USD.KRAKEN`, `ETH/USD.KRAKEN`; BINANCE = `BTCUSDT.BINANCE`, `ETHUSDT.BINANCE`.
- Windows as bar closes. Daily: train 2017-01-02 .. 2023-01-01 (2191 closes), validate 2023-01-02 .. 2024-07-01
  (547). Hourly: train 2017-01-01 01:00 .. 2023-01-01 00:00 (52584), validate 2023-01-01 01:00 .. 2024-07-01
  00:00 (13128).

## Daily bars (the study's bars)

| Source | Window | Grid closes | Common closes | First | Last | Dropped: BTC bar, no ETH | Dropped: ETH bar, no BTC | Neither has a bar |
|---|---|---|---|---|---|---|---|---|
| KRAKEN | train | 2191 | **2190** | 2017-01-02 | 2023-01-01 | 1: close 2018-01-13 | 0 | 0 |
| KRAKEN | validate | 547 | **547** | 2023-01-02 | 2024-07-01 | 0 | 0 | 0 |
| BINANCE | train | 2191 | **1963** | 2017-08-18 | 2023-01-01 | 0 | 0 | 228 (late start: 2017-01-02 .. 2017-08-17); 0 inside |
| BINANCE | validate | 547 | **547** | 2023-01-02 | 2024-07-01 | 0 | 0 | 0 |

Panel rows over both windows: KRAKEN 2737 and BINANCE 2510.

- **KRAKEN, close 2018-01-13** (the bar of day 2018-01-12): `ETH/USD.KRAKEN` has no bar there. The build recorded
  the same gap (SNAPSHOT.json `checks.quality`: after 2018-01-12, before 2018-01-14, 1 missing). The panel drops
  BTC's bar at that close, so the rows for closes 2018-01-12 and 2018-01-14 are adjacent and 2 days apart. It is
  listed in `attrs["alignment"]["dropped"]["BTC"]` and `["missing"]`. Any rule that counts rows (e.g. a check
  every N rows) counts that 2-day step as one row.
- **BINANCE starts late:** both symbols' first daily close is 2017-08-18, so 228 train closes have no Binance
  bars. There is no gap after that. Kraken (the primary source, AGENTS.md) covers all of train.

## Hourly bars (counts only; dates are in `attrs["alignment"]`)

| Source | Window | Grid closes | Common closes | First | Last | Dropped BTC | Dropped ETH | Neither: late start / inside |
|---|---|---|---|---|---|---|---|---|
| KRAKEN | train | 52584 | 52467 | 2017-01-01 01:00 | 2023-01-01 00:00 | 56 | 3 | 0 / 58 |
| KRAKEN | validate | 13128 | 13115 | 2023-01-01 01:00 | 2024-07-01 00:00 | 1 | 0 | 0 / 12 |
| BINANCE | train | 52584 | 46934 | 2017-08-17 05:00 | 2023-01-01 00:00 | 2 | 0 | 5476 / 172 |
| BINANCE | validate | 13128 | 13126 | 2023-01-01 01:00 | 2024-07-01 00:00 | 0 | 0 | 0 / 2 |

Panel rows over both windows: KRAKEN 65582 and BINANCE 60060. In each row, grid closes = common + dropped BTC +
dropped ETH + neither.

## Command

From `/home/user/osprey`, `uv run python - <<'EOF'` with the following script. It reads only the panel's index
and `attrs["alignment"]`, never a price column.

```python
import pandas as pd

from lab.config import in_window, splits
from lab.data.panel import STEPS, load_panel

sp = splits()
for interval in ("1d", "1h"):
    for source in ("KRAKEN", "BINANCE"):
        p = load_panel(source, interval, last_close="2024-07-01")  # the last validate close, never later
        al, step = p.attrs["alignment"], STEPS[interval]
        print(source, interval, p.attrs["snapshot_id"], p.attrs["instruments"], "panel rows", len(p))
        for w in ("train", "validate"):
            grid = pd.date_range(sp[w][0] + step, sp[w][1] + pd.Timedelta(days=1), freq=step)
            idx = p.index[in_window(p.index, sp[w])]
            drop = {a: pd.DatetimeIndex(al["dropped"][a]["closes"]) for a in ("BTC", "ETH")}
            drop = {a: d[in_window(d, sp[w])] if len(d) else d for a, d in drop.items()}
            absent = grid[~grid.isin(idx)]
            neither = absent[~absent.isin(drop["BTC"]) & ~absent.isin(drop["ETH"])]
            late, early = (neither < idx[0]).sum(), (neither > idx[-1]).sum()
            print(f"  {w}: grid {len(grid)} ({grid[0]} .. {grid[-1]}), common {len(idx)}, first {idx[0]}, "
                  f"last {idx[-1]}, dropped BTC {len(drop['BTC'])}, dropped ETH {len(drop['ETH'])}, neither: "
                  f"late start {late}, early end {early}, inside {len(neither) - late - early}")
            if interval == "1d":
                print("    dropped:", {a: [str(t.date()) for t in d] for a, d in drop.items()},
                      "neither inside:", [str(t.date()) for t in neither[(neither > idx[0]) & (neither < idx[-1])]])
```

"Early end" was 0 everywhere: every panel's last close is 2024-07-01 00:00.
