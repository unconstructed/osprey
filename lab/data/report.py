"""The data quality report (``reports/data/<YYYY-MM-DD>.md``), rendered from a snapshot dict alone.

Everything in the report comes from ``SNAPSHOT.json``, so the report can be regenerated from it and no
number is typed by hand.
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
        f"- Bars content SHA-256: `{snap['content_sha256']}`",
        "",
    ]
    lines += _sources(snap) + _coverage(snap) + _bad_ticks(snap) + _intervals(snap) + _cross(snap) + _alignment(snap)
    lines += _round_trip(snap)
    lines += ["## 8. Open items", ""] + [f"- {item}" for item in OPEN_ITEMS] + [""]
    return "\n".join(lines)


def write_report(snap: dict, report_dir: str | Path) -> Path:
    """Write ``<report_dir>/<snapshot created date>.md`` and return its path."""
    path = Path(report_dir) / f"{snap['created'][:10]}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report(snap))
    return path
