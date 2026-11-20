"""The data quality reports, rendered from a snapshot dict alone: ``reports/data/<YYYY-MM-DD>.md`` (bars) and,
for a snapshot with positioning data, ``reports/data/<YYYY-MM-DD>-positioning.md``.

Everything in the reports comes from ``SNAPSHOT.json``, so they can be regenerated from it and no number is
typed by hand. A report file of another snapshot is never overwritten (:func:`report_path`).
"""

from __future__ import annotations

from pathlib import Path

MAX_LIST = 50  # longest inline lists (bar timestamps); the full lists are in SNAPSHOT.json

OPEN_ITEMS = [
    "**Base cbBTC/USDC vs Coinbase BTC/USD price gap: not measured.** No Base data source (and no 0x quote "
    "endpoint) is on the network allow-list, so the gap can't be measured from the allowed sources. It is "
    "not estimated here. Measuring it needs the owner to allow a Base data source.",
    "**DEX cost measurement (0x quotes on Base, Base gas): not done**, for the same reason. "
    "`config/costs.yaml` keeps its pessimistic placeholders; no change is proposed.",
    "**Kraken whole-archive SHA-256: not verified.** The archive is read by HTTP range requests and never "
    "held, so the published part SHA-256 sums can't be checked. What is verified: each member's CRC-32 and "
    "size, and every range answer carried the part's ETag from the start of the read.",
    "**Coinbase candles have no published checksum.** The pages are stored as received and hashed. Complete "
    "pages are not fetched again, and the newest page is re-fetched on each online build, which changes the "
    "snapshot ID.",
    "**Binance quotes in USDT, not USD.** The Binance/USD differences in the cross-check include the USDT/USD "
    "rate. The allowed sources have no USDT/USD series in this build to separate the two.",
]


def _fmt(x, digits: int = 4) -> str:
    if x is None:
        return "n/a"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.{digits}g}"
    return str(x)


def _price(x) -> str:
    """A price as its shortest exact decimal (never rounded for display)."""
    return "n/a" if x is None else repr(float(x))


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:+.3f}%"


def _table(header: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(_fmt(c) for c in row) + " |" for row in rows]
    return out + [""]


def _list(items: list, limit: int = MAX_LIST) -> str:
    if not items:
        return "none"
    shown = ", ".join(str(x) for x in items[:limit])
    return shown + (f" ... (+{len(items) - limit} more in SNAPSHOT.json)" if len(items) > limit else "")


def _sources(snap: dict) -> list[str]:
    out = ["## 1. Sources and what was verified", ""]
    for name, src in snap["sources"].items():
        files, details = src["files"], src.get("details", {})
        out += [f"### {name}", "", src["note"], ""]
        out += [f"- Raw files hashed: {len(files)} ({sum(f['bytes'] for f in files):,} bytes)"]
        if name == "kraken":
            arc = details["archive"]
            out += [
                f"- {details['action']}",
                f"- Verified: {details['verified']}",
                f"- Archive: {len(arc['parts'])} parts, {arc['total_bytes']:,} bytes, {arc['members_in_archive']} "
                f"members; read with {arc['range_requests']} range requests ({arc['bytes_fetched']:,} bytes) "
                f"on {details['extracted_at']}",
                f"- Manifest: coverage {details['manifest'].get('coverage')}, generated "
                f"{details['manifest'].get('generated')}, release {details['manifest'].get('release')}",
                "",
            ]
            out += _table(
                ["Part", "Bytes", "ETag", "Published SHA-256 (not checked)"],
                [
                    [p["url"].rsplit("/", 1)[-1], f"{p['bytes']:,}", p["etag"],
                     arc["published_sha256"].get(p["url"].rsplit("/", 1)[-1])]
                    for p in arc["parts"]
                ],
            )
            out += _table(
                ["Member", "Bytes", "CRC-32 (checked)", "SHA-256"],
                [[n, f"{m['file_size']:,}", m["crc32"], m["sha256"]] for n, m in sorted(details["members"].items())],
            )
        elif name == "binance":
            out += [
                f"- Months {details['months']}: {details['zips']} zips; status {details['status']}",
                f"- {details['verified']}",
                f"- Missing months: {_list(details['missing'])}",
                "",
            ]
        elif name == "binance_futures":
            out += [
                f"- Up to {details['last_day']} (the validate window's last day): {details['zips']} zips; status "
                f"{details['status']}",
                f"- {details['verified']}",
                f"- Missing files: {_list(details['missing'])}",
                "- Positioning series, checks and point-in-time rules: the positioning report of this snapshot",
                "",
            ]
        else:
            out += [f"- {details['pages']} pages ({details['fetched_now']} fetched in this build)",
                    f"- Verified: {details['verified']}", ""]
    return out


def _coverage(snap: dict) -> list[str]:
    q = snap["checks"]["quality"]
    rows = [
        [s["bar_type"], s["rows"], s["start"], s["end"], q[s["bar_type"]]["expected_bars"], s["gaps"],
         s["missing_bars"], q[s["bar_type"]]["off_grid"], s["price_precision"]]
        for s in snap["series"]
    ]
    out = ["## 2. Coverage per series", "", "Timestamps are bar CLOSE times (UTC).", ""]
    out += _table(
        ["Bar type", "Rows", "First bar", "Last bar", "Expected", "Gaps", "Missing bars", "Off grid", "Price dp"], rows
    )
    out += ["## 3. Gaps (never filled)", ""]
    for s in snap["series"]:
        gaps = q[s["bar_type"]]["longest_gaps"]
        out.append(f"- `{s['bar_type']}`: {s['gaps']} gaps, {s['missing_bars']} missing bars. Longest: "
                   + _list([f"{g['after']} -> {g['before']} ({g['missing']} missing)" for g in gaps[:5]], 5))
    return out + [""]


def _bad_ticks(snap: dict) -> list[str]:
    q, load = snap["checks"]["quality"], snap["checks"]["loading"]
    out = ["## 4. Bad ticks and removed bars", "",
           "Removed by loading: rows that aren't valid bars (non-positive price, OHLC inconsistent, bad timestamp "
           "or bar length), duplicates (the last row wins), Binance bars whose open is off the interval grid, and "
           "zero-volume bars (exchange placeholders for intervals without trades). The checks then rerun on what "
           "stays; extreme moves and stale closes are flagged, not removed.", ""]
    rows = []
    for s in snap["series"]:
        bt, ld, qq = s["bar_type"], load[s["bar_type"]], q[s["bar_type"]]
        rows.append([bt, ld.get("rows_read"), ld.get("dropped_bad"), ld.get("dropped_duplicates"),
                     ld.get("dropped_off_grid", 0), len(ld.get("short_bars", [])), ld["dropped_zero_volume"],
                     qq["non_positive"] + qq["ohlc_inconsistent"], qq["extreme_moves"], qq["extreme_wicks"],
                     qq["stale_runs"]])
    out += _table(["Bar type", "Rows read", "Bad dropped", "Duplicates dropped", "Off-grid dropped",
                   "Short bars kept", "Zero-volume dropped", "Bad left", "Extreme moves", "Extreme wicks",
                   "Stale runs"], rows)
    for s in snap["series"]:
        bt, ld, qq = s["bar_type"], load[s["bar_type"]], q[s["bar_type"]]
        lines = []
        if ld.get("off_grid_opens"):
            lines.append(f"off-grid opens dropped: {_list(ld['off_grid_opens'])}")
        if ld.get("short_bars"):
            lines.append("short bars kept (open, seconds): " + _list([f"{a} ({b}s)" for a, b in ld["short_bars"]]))
        if ld["zero_volume_bars"]:
            lines.append(f"zero-volume bars dropped: {_list(ld['zero_volume_bars'])}")
        if qq["extreme_moves_top"]:
            lines.append("largest moves: " + _list(
                [f"{m['ts']} (log {m['log']:+.4f}, {m['k']} sigma)" for m in qq["extreme_moves_top"]], 5))
        if qq["extreme_wicks_top"]:
            lines.append("largest wicks: " + _list(
                [f"{m['ts']} (log {m['log']:.4f}, {m['k']} sigma)" for m in qq["extreme_wicks_top"]], 5))
        if qq["longest_stale"]:
            st = qq["longest_stale"]
            lines.append(f"longest stale close: {st['unchanged_bars']} bars unchanged, {st['from']} -> {st['to']}")
        if lines:
            out.append(f"- `{bt}`: " + "; ".join(lines))
    return out + [""]


def _intervals(snap: dict) -> list[str]:
    dh = snap["checks"]["daily_vs_hourly"]
    out = ["## 5. Daily bars vs hourly bars of the same source", "",
           "Hourly bars aggregated to UTC days (`loaders.resample`) against the daily bars: OHLC should be "
           "identical, which also confirms both are on UTC days.", ""]
    rows = [[inst, r["days_compared"], r["daily_without_hourly"], r["mismatches"]["open"], r["mismatches"]["high"],
             r["mismatches"]["low"], r["mismatches"]["close"], r["volume_max_rel_diff"]] for inst, r in dh.items()]
    out += _table(["Instrument", "Days compared", "Daily without hourly", "Open diff", "High diff", "Low diff",
                   "Close diff", "Max volume rel diff"], rows)
    for inst, r in dh.items():
        for m in r["mismatched_days"]:
            out.append(f"- `{inst}` {m['ts']}: daily OHLC {m['daily']} vs from hourly {m['from_hourly']}")
    return out + [""]


def _cross(snap: dict) -> list[str]:
    out = ["## 6. Cross-check of daily closes between sources", ""]
    cc = snap["checks"]["cross_check"]
    if not cc:
        return out + ["Not run: fewer than two sources with daily bars.", ""]
    for coin, r in cc.items():
        out += [f"### {coin}", "",
                f"Tolerance {100 * r['tolerance']:g}%: a day is an outlier when two sources' closes differ by "
                "more than that. Kraken and Coinbase quote USD and Binance quotes USDT, so the Binance pairs include "
                "the USDT/USD basis (per-year medians below). Day = the bar's UTC trading day (close time - 1 day).",
                ""]
        out += _table(["Pair", "Days", "Median diff", "p99 abs diff", "Max abs diff", "Max on", "Outliers"],
                      [[p["pair"], p["days"], _pct(p["median"]), _pct(p["p99_abs"]), _pct(p["max_abs"]),
                        p["max_day"], p["outliers"]] for p in r["pairs"]])
        years = sorted({y for p in r["pairs"] for y in p["median_by_year"]})
        out += _table(["Pair"] + [str(y) for y in years],
                      [[p["pair"]] + [_pct(p["median_by_year"].get(y)) for y in years] for p in r["pairs"]])
        out += [f"Every outlier ({len(r['outliers'])} days). Hourly bars = how many of the day's 24 hourly bars "
                "each source with hourly data has (fewer means the venue had no trades for a while, so its daily "
                "close is older than midnight):", ""]
        if r["outliers"]:
            names = r["sources"]
            out += _table(["Day"] + names + ["Pairs outside tolerance", "Hourly bars"],
                          [[o["day"]] + [_price(o["values"].get(n)) for n in names]
                           + ["; ".join(f"{k} {_pct(v)}" for k, v in o["pairs"].items()),
                              ", ".join(f"{k} {v}" for k, v in o.get("hourly_bars", {}).items()) or "n/a"]
                           for o in r["outliers"]])
        else:
            out += ["none", ""]
    return out


def _alignment(snap: dict) -> list[str]:
    out = ["## 6a. Time alignment between sources", "",
           "Median |log(a / b)| of the closes with `a` shifted by k bars. The minimum must be at k = 0 (the build "
           "stops otherwise): it shows both sources label the same instant with the same timestamp.", ""]
    rows = []
    for coin, by_interval in snap["checks"].get("alignment", {}).items():
        for interval, pairs in by_interval.items():
            for pair, r in pairs.items():
                m = r["median_abs_log_diff"]
                rows.append([coin, interval, pair, r["best_lag"]] + [m.get(k) for k in ("-1", "0", "1")])
    if not rows:
        return out + ["Not run: fewer than two sources.", ""]
    return out + _table(["Coin", "Bars", "Pair", "Best shift", "k = -1", "k = 0", "k = +1"], rows)


def _round_trip(snap: dict) -> list[str]:
    rt, cov = snap["checks"]["round_trip"], snap["checks"]["train_coverage"]
    out = ["## 7. Catalog round trip and train-window coverage", "",
           "Every series was read back with `lab.data.catalog.load_bars` and compared with what was written: "
           "equal means bit for bit equal to `float(Price)` / `float(Quantity)` of the written bars (the live "
           "conversion). Distance from the source floats: prices in units in the last place (0 or 1 expected), "
           "volumes rounded to 8 decimals.", ""]
    out += _table(["Bar type", "Rows", "Equal", "Price dp", "Max price ulps vs source", "Max volume rounding"],
                  [[bt, r["rows"], r["exact"], r["price_precision"], r["max_price_ulps_vs_source"],
                    r["max_volume_rounding"]] for bt, r in rt.items()])
    out += ["Train window (config/splits.yaml; bars closing after the first midnight up to the midnight after "
            "the last day):", ""]
    out += _table(["Bar type", "Expected", "Present", "First in window", "Late start (bars)", "Missing inside",
                   "Spans window", "Complete"],
                  [[bt, c["expected"], c["present"], c["first"], c["late_start_bars"], c["missing_inside"],
                    c["covered"], c["complete"]] for bt, c in cov.items()])
    late = [f"`{bt}` starts {c['late_start_bars']} bars late (first bar {c['first']})"
            for bt, c in cov.items() if c["late_start_bars"] > 0]
    early = [f"`{bt}` ends {c['early_end_bars']} bars early (last bar {c['last']})"
             for bt, c in cov.items() if c["early_end_bars"] > 0]
    out += ["Not covering the whole train window: " + ("; ".join(late + early) if late or early else "none") + ".", ""]
    out += ["Bars missing inside the train window (every gap; bar close times, never filled):", ""]
    for bt, c in cov.items():
        if c["missing_inside"]:
            gaps = [f"{g['after']} -> {g['before']} ({g['missing']})" for g in c["gaps"]]
            out.append(f"- `{bt}`: {c['missing_inside']} bars in {len(gaps)} gaps: " + _list(gaps, 1000))
    return out + [""]


def _content_line(snap: dict) -> str:
    bars = snap.get("bars_content_sha256", snap["content_sha256"])
    if bars == snap["content_sha256"]:
        return f"- Bars content SHA-256: `{bars}`"
    return f"- Content SHA-256 (bars and positioning tables): `{snap['content_sha256']}`; bars only: `{bars}`"


def render_report(snap: dict) -> str:
    build = snap["build"]
    code = build["code"]
    lines = [
        f"# Data quality report, snapshot `{snap['snapshot_id']}`",
        "",
        f"- Created: {snap['created']} (UTC), {'offline rebuild from data/raw' if build['offline'] else 'online build'}",
        f"- Command: `uv run python -m lab.data.build --sources {','.join(build['sources'])} --coins "
        f"{','.join(build['coins'])} --intervals {','.join(build['intervals'])} "
        f"--tolerance {float(build['tolerance'])!r}{' --offline' if build['offline'] else ''}`",
        f"- Code: commit `{code['commit']}`, lab/ with uncommitted changes: {_fmt(code['lab_dirty'])}",
        f"- Snapshot ID rule: {snap['id_rule']}; raw files: "
        f"{sum(len(s['files']) for s in snap['sources'].values())}",
        _content_line(snap),
        "",
    ]
    lines += _sources(snap) + _coverage(snap) + _bad_ticks(snap) + _intervals(snap) + _cross(snap) + _alignment(snap)
    lines += _round_trip(snap)
    lines += ["## 8. Open items", ""] + [f"- {item}" for item in OPEN_ITEMS] + [""]
    return "\n".join(lines)


def report_path(report_dir: str | Path, snap: dict, suffix: str = "") -> Path:
    """``<report_dir>/<created date><suffix>.md``, unless that file is the report of ANOTHER snapshot (its first
    line doesn't name this snapshot's ID): then ``<created date><suffix>-<snapshot id>.md``, so a second
    snapshot built the same day never overwrites the first one's report."""
    path = Path(report_dir) / f"{snap['created'][:10]}{suffix}.md"
    if path.is_file():
        first = path.read_text().partition("\n")[0]
        if f"`{snap['snapshot_id']}`" not in first:
            path = path.with_name(f"{path.stem}-{snap['snapshot_id']}.md")
    return path


def write_report(snap: dict, report_dir: str | Path) -> Path:
    """Write the bars report to :func:`report_path` and return its path."""
    path = report_path(report_dir, snap)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(snap))
    return path


# --------------------------------------------------------------------------- positioning report

TAKER_MEANING = {-5: "period ending at T", 0: "period starting at T"}


def _offset(k, meaning: dict | None = None) -> str:
    if k is None:
        return "inconclusive"
    if meaning is not None:
        return meaning.get(k, f"period starting at T{k:+d} min")
    return "price at T" if k == 0 else f"price at T{k:+d} min"


def _pos_files(snap: dict) -> list[str]:
    d = snap["sources"]["binance_futures"]["details"]
    out = ["## 1. Files and what was verified", "",
           f"Every zip's SHA-256 matched its published `.CHECKSUM`; files were requested up to {d['last_day']} "
           f"(the validate window's last day) and no later. Status: {d['status']}. Missing: {_list(d['missing'])}.",
           ""]
    starts = d["starts"]
    rows = []
    for name, p in d["periods"].items():
        start = starts.get(name) if isinstance(starts, dict) else None
        before = "n/a" if start is None else f"{start['before']}: {'published' if start['before_published'] else 'not published (404)'}"
        rows.append([name] + ([p["first"], p["last"], p["asked"]] if p else ["none", "none", 0]) + [before])
    out += _table(["Series", "First file", "Last file", "Files asked for", "Period before the first (online check)"],
                  rows)
    if not isinstance(starts, dict):
        out += [f"Start check: {starts}.", ""]
    return out


def _pos_coverage(snap: dict) -> list[str]:
    q = snap["checks"]["external"]
    out = ["## 2. Stored series", "",
           "`ts` is the source's timestamp, `known_at` when the value became public (section 3). Missing = funding "
           "events or 5-minute rows absent between the first and the last (never filled).", ""]
    rows = []
    for e in snap["external"]:
        c = q[f"{e['symbol']} {e['table']}"]
        rows.append([f"{e['symbol']} {e['table']}", e["rows"], e["first_ts"], e["last_ts"], e["last_known_at"],
                     c["gaps"], c["missing"], e["path"]])
    out += _table(["Series", "Rows", "First ts", "Last ts", "Last known_at", "Gaps", "Missing", "File"], rows)
    out += ["Daily bar closes of each split window that get a value from `external.positioning_at` (first such "
            "close in brackets). The test window is not stored.", ""]
    cols = ["funding_last", "funding_mean_7d", "oi_last", "oi_change_7d", "ls_account_last", "ls_top_position_last"]
    rows = []
    for sym, windows in snap["checks"]["positioning_coverage"].items():
        for name, w in windows.items():
            cells = []
            for col in cols:
                c = w["columns"][col]
                cells.append(f"{c['closes']} ({c['first'][:10]})" if c["first"] else "0")
            rows.append([sym, name, w["closes"]] + cells)
    out += _table(["Symbol", "Window", "Daily closes"] + cols, rows)
    return out


def _pos_timing(snap: dict) -> list[str]:
    pos = snap["positioning"]
    out = ["## 3. When a value is known (point in time)", "",
           f"Only values known strictly before a bar's close are used for that bar; stored values are all known "
           f"before {pos['cut']} ({pos['cut_rule']}).", ""]
    out += [f"- `{k}`: {v}" for k, v in pos["rules"].items()] + [""]
    out += ["Timestamp check of the metrics against 5-minute futures klines, per UTC day: which kline period the "
            "row's taker buy/sell ratio equals, and which moment's price its open-interest value / open interest "
            f"equals. Data reach = how far past T a day's data go; the known_at lag is {pos['metrics_lag']}, and "
            "the build stops if any day reaches further.", ""]
    rows = []
    for sym, t in snap["checks"]["metrics_timing"].items():
        for r in t["runs"]:
            reach = [k + 5 for k in [r["taker_offset"]] if k is not None]
            reach += [k for k in [r["price_offset"]] if k is not None]
            rows.append([sym, r["from"], r["to"], r["days"], _offset(r["taker_offset"], TAKER_MEANING),
                         _offset(r["price_offset"]), f"T{max(reach):+d} min" if reach else "n/a"])
    out += _table(["Symbol", "From", "To", "Days", "Taker ratio matches", "OI value / OI matches", "Data reach"],
                  rows)
    out += ["Days with no conclusive check: " + ", ".join(
        f"{sym} {t['inconclusive_days']}" for sym, t in snap["checks"]["metrics_timing"].items()) + "; furthest "
        "reach: " + ", ".join(f"{sym} {_fmt(t['max_reach_minutes'])} min" for sym, t in
                             snap["checks"]["metrics_timing"].items()) + ".", ""]
    return out


def _pos_cleaning(snap: dict) -> list[str]:
    out = ["## 4. Loading and cleaning", "",
           "Bad rows dropped; duplicates keep the last row; values that are empty or not positive (e.g. `0E-8`) "
           f"become NaN; a value unchanged for {snap['positioning']['stale_after']} or more becomes NaN from that "
           "moment on (frozen feed; the run's earlier rows are kept, as they could not be known to be frozen at "
           "their time). Nothing is filled.", ""]
    rows = []
    for sym, loading in snap["checks"]["external_loading"].items():
        for table in ("funding", "metrics"):
            ld = loading[table]
            rows.append([f"{sym} {table}", ld["files"], ld["rows_read"], ld["dropped_bad"], ld["exact_duplicates"],
                         ld["conflicting_duplicates"], ld["files_out_of_order"], ld["rows_outside_file_period"],
                         ld["dropped_known_at_or_after_cut"]])
    out += _table(["Series", "Files", "Rows read", "Bad dropped", "Exact duplicates", "Conflicting duplicates",
                   "Files out of time order", "Rows outside the file's period", "Known at/after the cut"], rows)
    rows = []
    for sym, loading in snap["checks"]["external_loading"].items():
        ld, fields = loading["metrics"], snap["checks"]["external"][f"{sym} metrics"]["fields"]
        for name, f in fields.items():
            absent = f["longest_absence"]
            rows.append([sym, name, f["rows"], ld[f"missing_{name}"], ld[f"invalid_{name}"], ld["stale_rows"][name],
                         "none" if absent is None else f"{absent['from']} -> {absent['to']} ({absent['rows']} rows)"])
    out += _table(["Symbol", "Field", "Rows with a value", "Empty", "Not positive", "Stale (frozen)",
                   "Longest stretch without a value"], rows)
    for sym, loading in snap["checks"]["external_loading"].items():
        runs = sorted(loading["metrics"]["stale_runs"], key=lambda r: (-r["rows"], r["from"]))
        out.append(f"- {sym}: {len(runs)} stale runs; longest: " + _list(
            [f"{r['field']} {r['from']} -> {r['to']} ({r['rows']} rows)" for r in runs], 8)
            + f"; open-interest value without open interest: {loading['metrics']['value_without_open_interest']}")
    return out + [""]


def _pos_values(snap: dict) -> list[str]:
    out = ["## 5. Gaps and values", ""]
    for name, c in snap["checks"]["external"].items():
        gaps = _list([f"{g['after']} -> {g['before']} ({g['missing']})" for g in c["longest_gaps"]], 10)
        if "rate" in c:
            r = c["rate"]
            out.append(f"- `{name}`: {c['gaps']} gaps ({c['missing']} events missing): {gaps}. Intervals (hours: "
                       f"events) {c['interval_hours']}; instants {c['grid_offset_ms']['min']}..{c['grid_offset_ms']['max']} "
                       f"ms from the interval grid ({c['off_grid_over_1min']} over 1 min). Rate min {r['min']:.6g}, "
                       f"p1 {r['p01']:.6g}, median {r['median']:.6g}, p99 {r['p99']:.6g}, max {r['max']:.6g}; largest: "
                       + _list([f"{x['ts']} {x['rate']:+.6g}" for x in c["largest_abs"]], 5))
        else:
            moves = _list([f"{m['ts']} ({m['abs_log_change']})" for m in c["open_interest_largest_moves"]], 5)
            st = c["open_interest_longest_unchanged"]
            out.append(f"- `{name}`: {c['rows']} of {c['expected_rows']} 5-minute rows, {c['off_grid']} off the grid; "
                       f"{c['gaps']} gaps ({c['missing']} rows missing), {c['days_short']} of {c['days']} days short "
                       f"of 288 rows ({c['days_empty']} empty; the last day also lacks any row known only at or after "
                       f"the cut). Longest gaps: {gaps}. Largest 5-minute open-interest "
                       f"moves |log change| (kept: no causal rule tells a recovering feed from a real move): {moves}. "
                       "Longest unchanged open interest left after the stale rule: "
                       + ("none" if st is None else f"{st['rows']} rows, {st['from']} -> {st['to']}"))
    return out + [""]


def _pos_open(snap: dict) -> list[str]:
    starts = {e["symbol"]: {} for e in snap["external"]}
    for e in snap["external"]:
        starts[e["symbol"]][e["table"]] = e["first_ts"][:10]
    cov = snap["checks"]["positioning_coverage"]
    items = [
        "**Coverage is far shorter than the price history.** " + "; ".join(
            f"{sym}: funding from {s['funding']}, open interest and long/short ratios from {s['metrics']}; daily "
            f"closes of the train window with an open-interest value: {cov[sym]['train']['columns']['oi_last']['closes']} "
            f"of {cov[sym]['train']['closes']}" for sym, s in starts.items())
        + ". data.binance.vision publishes nothing earlier ("
        + ("checked in this build: the period before each first file answered 404"
           if isinstance(snap["sources"]["binance_futures"]["details"]["starts"], dict)
           else "not re-checked in this offline build; an online build checks that the period before each first "
           "file answers 404")
        + "). A model or rule using these series can only be trained and validated on that part of the history.",
        "**Publication delay of the live API not measured.** `known_at` adds no delay to funding (the rate is "
        f"fixed at the funding instant) and {snap['positioning']['metrics_lag']} to metrics (one 5-minute period; "
        "section 3). The futures API that would show the live delay (fapi.binance.com) is not on the network "
        "allow-list. For bar closes on the 5-minute grid the newest metrics row used was stamped at least 10 "
        "minutes before the close.",
        "**The test window was not downloaded.** Extending positioning data past "
        f"{snap['positioning']['cut'][:10]} is a separate, deliberate step for the backtest-auditor's one-time "
        "test run and for production; `load_positioning` refuses a later `end`.",
        "**USDT-margined perpetuals.** Funding rates are per 8-hour interval (a fraction, not annualised); open "
        "interest is in contracts (1 contract = 1 BTC or 1 ETH) and in USDT.",
    ]
    return ["## 6. Open items", ""] + [f"- {x}" for x in items] + [""]


def render_positioning_report(snap: dict, main_report: str | None = None) -> str:
    build, code = snap["build"], snap["build"]["code"]
    lines = [
        f"# Positioning data report, snapshot `{snap['snapshot_id']}`",
        "",
        f"- Created: {snap['created']} (UTC), {'offline rebuild from data/raw' if build['offline'] else 'online build'}",
        f"- Command: `uv run python -m lab.data.build --sources {','.join(build['sources'])} --coins "
        f"{','.join(build['coins'])} --intervals {','.join(build['intervals'])} "
        f"--tolerance {float(build['tolerance'])!r}{' --offline' if build['offline'] else ''}`",
        f"- Code: commit `{code['commit']}`, lab/ with uncommitted changes: {_fmt(code['lab_dirty'])}",
        f"- Bars of this snapshot and their checks: {main_report or 'the data quality report of this snapshot'}",
        "- Load with `lab.data.external.load_positioning(symbol, freq, start, end)`: one row per bar close, only "
        "values known before it, never past the validate window.",
        "",
    ]
    lines += _pos_files(snap) + _pos_coverage(snap) + _pos_timing(snap) + _pos_cleaning(snap) + _pos_values(snap)
    lines += _pos_open(snap)
    return "\n".join(lines)


def write_positioning_report(snap: dict, report_dir: str | Path, main_report: str | None = None) -> Path:
    """Write the positioning report to :func:`report_path` (suffix ``-positioning``) and return its path."""
    path = report_path(report_dir, snap, "-positioning")
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None if main_report is None else f"`{Path(main_report).name}`"
    path.write_text(render_positioning_report(snap, name))
    return path
