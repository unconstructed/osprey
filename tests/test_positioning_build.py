"""Positioning data in the build: lab/data/sources.download_binance_futures, the build with
``--sources ...,binance_futures``, SNAPSHOT.json, the stored tables and the reports. No network: a fake
data.binance.vision (httpx.MockTransport) serves funding, metrics and 5-minute kline zips around the end of the
validate window (2024-06-30). The July 2024 files exist on the fake server; the build must never ask for them.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from test_data_build import Server, World, cfg_for

from lab.data import build as b
from lab.data import catalog as cat
from lab.data import external as ext
from lab.data import futures as fu
from lab.data import report as rep
from lab.data import sources as src

NOW = datetime(2024, 7, 20, 12, tzinfo=UTC)
FIRST = {
    "funding": {"BTC": date(2024, 5, 1), "ETH": date(2024, 5, 1)},
    "metrics": {"BTC": date(2024, 6, 27), "ETH": date(2024, 6, 28)},
}
MISSING_DAY = ("ETH", "2024-06-29")  # not published: listed, never filled
SWITCH = pd.Timestamp("2024-06-29", tz="UTC")  # from this day create_time is the START of the 5-minute period


def zip_bytes(name: str, lines: list[str]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(name.replace(".zip", ".csv"), "\n".join(lines) + "\n")
    return buf.getvalue()


def klines(seed: int) -> pd.DataFrame:
    """5-minute klines for June and July 2024 (period start index)."""
    idx = pd.date_range("2024-06-01", "2024-07-31 23:55", freq="5min", tz="UTC")
    rng = np.random.default_rng(seed)
    close = np.round(60000 * np.exp(np.cumsum(rng.normal(0, 0.001, len(idx)))), 1)
    volume = np.round(rng.uniform(50, 150, len(idx)), 3)
    taker = np.round(volume * rng.uniform(0.2, 0.8, len(idx)), 3)
    return pd.DataFrame({"open": np.concatenate([[60000.0], close[:-1]]), "close": close, "volume": volume,
                         "taker": taker}, index=idx)


class FuturesWorld:
    """Fake data.binance.vision futures files for BTC and ETH, May to July 2024."""

    def __init__(self):
        self.routes: dict[str, bytes] = {}
        self.klines = {"BTC": klines(11), "ETH": klines(12)}
        for coin in ("BTC", "ETH"):
            sym = src.BINANCE_SYMBOLS[coin]
            for month in ("2024-05", "2024-06", "2024-07"):
                start = pd.Timestamp(month + "-01", tz="UTC")
                times = pd.date_range(start, start + pd.offsets.MonthBegin(1), freq="8h", inclusive="left")
                rng = np.random.default_rng(len(self.routes))
                lines = [",".join(fu.FUNDING_HEADER)] + [
                    f"{t.value // 1_000_000 + int(rng.integers(0, 40))},8,{rng.normal(1e-4, 2e-4):.8f}" for t in times]
                self.add("funding", coin, month, lines)
            k = self.klines[coin]
            ratio = k["taker"] / (k["volume"] - k["taker"])
            for day in pd.date_range(FIRST["metrics"][coin], "2024-07-01", freq="D", tz="UTC"):
                if (coin, day.date().isoformat()) == MISSING_DAY:
                    continue
                stamps = pd.date_range(day, periods=288, freq="5min")
                start_convention = day >= SWITCH
                taker = ratio.reindex(stamps + pd.Timedelta(minutes=0 if start_convention else -5))
                price = k["open"].reindex(stamps + pd.Timedelta(minutes=5 if start_convention else 0))
                oi = 80000 + np.arange(288) * 3.25
                lines = [",".join(fu.METRICS_HEADER)] + [
                    f"{t:%Y-%m-%d %H:%M:%S},{sym},{o:.3f},{o * p:.6f},1.5,1.4,1.3,{r:.8f}"
                    for t, o, p, r in zip(stamps, oi, price.to_numpy(), taker.to_numpy(), strict=True)
                ]
                lines = [x.replace(",nan", ",") for x in lines]  # no price after the last kline: empty field
                self.add("metrics", coin, day.date().isoformat(), lines[:1] + lines[1:][::-1])  # newest first
            for month in ("2024-06", "2024-07"):
                kk = k[k.index.strftime("%Y-%m") == month]
                lines = [f"{t.value // 1_000_000},{r.open},{max(r.open, r.close)},{min(r.open, r.close)},{r.close},"
                         f"{r.volume},{t.value // 1_000_000 + 299_999},0,10,{r.taker},0,0" for t, r in kk.iterrows()]
                self.add("klines_5m", coin, month, lines)

    def add(self, kind: str, coin: str, period: str, lines: list[str]) -> None:
        name, url = src.futures_file(kind, coin, period)
        data = zip_bytes(name, lines)
        self.routes[url] = data
        self.routes[url + ".CHECKSUM"] = f"{hashlib.sha256(data).hexdigest()}  {name}\n".encode()

    def server(self, extra: dict | None = None) -> Server:
        return Server({**self.routes, **(extra or {})})


@pytest.fixture(scope="module")
def fworld() -> FuturesWorld:
    return FuturesWorld()


@pytest.fixture
def first(monkeypatch):
    monkeypatch.setattr(src, "FUTURES_FIRST", FIRST)


def no_july(server: Server) -> bool:
    return not any("2024-07" in url for _, url, _ in server.log)


# ============================================================================ periods and URLs


def test_periods_and_file_names():
    assert src.futures_periods("metrics", date(2024, 6, 29), date(2024, 7, 1)) == ["2024-06-29", "2024-06-30",
                                                                                  "2024-07-01"]
    assert src.futures_periods("funding", date(2024, 5, 1), date(2024, 6, 30)) == ["2024-05", "2024-06"]
    assert src.futures_periods("funding", date(2024, 5, 1), date(2024, 6, 29)) == ["2024-05"]  # June not over
    assert src.futures_periods("klines_5m", date(2023, 12, 1), date(2024, 1, 15)) == ["2023-12"]
    assert src.futures_periods("metrics", date(2024, 7, 2), date(2024, 7, 1)) == []
    assert src._period_before("metrics", date(2024, 1, 1)) == "2023-12-31"
    assert src._period_before("funding", date(2024, 1, 1)) == "2023-12"
    assert src._period_before("funding", date(2024, 6, 1)) == "2024-05"
    assert src.futures_file("klines_5m", "ETH", "2024-06") == (
        "ETHUSDT-5m-2024-06.zip", "https://data.binance.vision/data/futures/um/monthly/klines/ETHUSDT/5m/ETHUSDT-5m-2024-06.zip")
    assert src.futures_file("metrics", "BTC", "2024-06-30")[1] == (
        "https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/BTCUSDT-metrics-2024-06-30.zip")
    assert src.futures_file("funding", "BTC", "2024-06")[1] == (
        "https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/BTCUSDT-fundingRate-2024-06.zip")
    assert src.FUTURES_FIRST["metrics"] == {"BTC": date(2020, 9, 1), "ETH": date(2021, 12, 1)}


# ============================================================================ download


def test_download_verifies_everything_and_never_passes_the_last_day(fworld, tmp_path):
    server = fworld.server()
    with server.client() as c:
        out = src.download_binance_futures(c, tmp_path, ["BTC", "ETH"], last_day=date(2024, 6, 30), first=FIRST)
    assert no_july(server)
    assert out.notes["missing"] == ["ETHUSDT-metrics-2024-06-29"]
    assert out.notes["status"] == {"downloaded and verified": 12, "missing": 1}
    assert out.notes["periods"]["BTCUSDT metrics"] == {"first": "2024-06-27", "last": "2024-06-30", "asked": 4}
    assert out.notes["periods"]["ETHUSDT klines_5m"] == {"first": "2024-06", "last": "2024-06", "asked": 1}
    assert out.notes["starts"]["ETHUSDT metrics"] == {"first": "2024-06-28", "before": "2024-06-27",
                                                      "before_published": False}
    assert out.notes["starts"]["BTCUSDT funding"]["before"] == "2024-04" and out.notes["zips"] == 12
    assert [p.name for p in out.series[("ETH", "metrics")]] == ["ETHUSDT-metrics-2024-06-28.zip",
                                                                "ETHUSDT-metrics-2024-06-30.zip"]
    assert len(out.files) == 24  # BTC: 2 funding + 4 metrics + 1 klines; ETH: 2 + 2 + 1; each with its checksum
    for f in out.files:  # every stored zip and checksum is the served file
        url = next(u for u in fworld.routes if u.endswith("/" + f.path.name))
        assert f.path.read_bytes() == fworld.routes[url] and f.path.parent.parent.name in ("BTCUSDT", "ETHUSDT")
    again = fworld.server()
    with again.client() as c:
        out2 = src.download_binance_futures(c, tmp_path, ["BTC", "ETH"], last_day=date(2024, 6, 30), first=FIRST)
    assert out2.notes["status"] == {"verified on disk": 12, "missing": 1}
    assert all(u.endswith(".CHECKSUM") for u in again.gets())  # start checks and the missing day only
    offline = src.download_binance_futures(None, tmp_path, ["BTC"], last_day=date(2024, 6, 30), first=FIRST)
    assert offline.notes["starts"] == "not checked (offline build)" and offline.notes["missing"] == []


def test_download_stops_when_history_starts_earlier_than_recorded(fworld, tmp_path):
    name, url = src.futures_file("metrics", "BTC", "2024-06-26")
    server = fworld.server({url + ".CHECKSUM": f"{'0' * 64}  {name}\n".encode()})
    with server.client() as c, pytest.raises(src.DownloadError, match="metrics for BTC now starts before 2024-06-27"):
        src.download_binance_futures(c, tmp_path, ["BTC"], last_day=date(2024, 6, 30), first=FIRST)


def test_download_with_nothing_to_fetch(tmp_path):
    out = src.download_binance_futures(None, tmp_path, ["ETH"], last_day=date(2024, 4, 30), first=FIRST)
    assert out.notes["periods"]["ETHUSDT metrics"] is None and out.series == {} and out.notes["zips"] == 0


def test_ext_last_day():
    assert b.ext_last_day(NOW) == date(2024, 6, 30)  # the validate window's last day (config/splits.yaml)
    assert b.ext_last_day(datetime(2024, 6, 29, 12, tzinfo=UTC)) == date(2024, 6, 28)


# ============================================================================ the build


@pytest.fixture(scope="module")
def kworld() -> World:
    return World()


@pytest.fixture(scope="module")
def built(fworld, kworld, tmp_path_factory):
    """Kraken bars (2017, from the bars test world) plus the positioning data, one online build."""
    root = tmp_path_factory.mktemp("positioning")
    mp = pytest.MonkeyPatch()
    mp.setattr(src, "FUTURES_FIRST", FIRST)
    server = Server({**kworld.routes, **fworld.routes})
    try:
        with server.client() as c:
            result = b.build(cfg_for(root, sources=("kraken", "binance_futures")), client=c, now=NOW)
    finally:
        mp.undo()
    return root, result, server


def test_build_stores_positioning_and_never_requests_the_test_window(built, fworld):
    root, result, server = built
    assert no_july(server)
    catalog = root / "data" / "catalog"
    snap = json.loads((catalog / cat.SNAPSHOT_FILE).read_text())
    all_files = [f for s in snap["sources"].values() for f in s["files"]]
    assert snap["snapshot_id"] == b.compute_snapshot_id(f["sha256"] for f in all_files)
    assert len(snap["sources"]["binance_futures"]["files"]) == 24 and snap["build"]["sources"] == ["kraken", "binance_futures"]
    assert [(e["symbol"], e["table"]) for e in snap["external"]] == [
        ("BTCUSDT", "funding"), ("BTCUSDT", "metrics"), ("ETHUSDT", "funding"), ("ETHUSDT", "metrics")]
    btc_m = next(e for e in snap["external"] if e["symbol"] == "BTCUSDT" and e["table"] == "metrics")
    assert btc_m["last_ts"] == "2024-06-30T23:50:00+00:00" and btc_m["last_known_at"] == "2024-06-30T23:55:00+00:00"
    assert btc_m["rows"] == 4 * 288 - 1  # the 23:55 row is known only at the cut
    assert snap["checks"]["external_loading"]["BTCUSDT"]["metrics"]["dropped_known_at_or_after_cut"] == 1
    assert snap["checks"]["external_loading"]["BTCUSDT"]["metrics"]["files_out_of_order"] == 4
    assert snap["positioning"]["cut"] == "2024-07-01T00:00:00+00:00" and snap["positioning"]["metrics_lag"] == "5 min"
    timing = snap["checks"]["metrics_timing"]["BTCUSDT"]
    assert timing["max_reach_minutes"] == 5 and timing["inconclusive_days"] == 0 and "days" not in timing
    assert [(r["from"], r["to"], r["taker_offset"], r["price_offset"]) for r in timing["runs"]] == [
        ("2024-06-27", "2024-06-28", -5, 0), ("2024-06-29", "2024-06-30", 0, 5)]
    cov = snap["checks"]["positioning_coverage"]["ETHUSDT"]
    assert cov["train"]["columns"]["oi_last"] == {"closes": 0, "first": None}
    assert cov["validate"]["columns"]["oi_last"] == {"closes": 2, "first": "2024-06-29T00:00:00+00:00"}
    # funding starts 2024-05-01 00:00 (+ a few ms): the first daily close that knows a rate is 2024-05-02
    assert cov["validate"]["columns"]["funding_last"] == {"closes": 61, "first": "2024-05-02T00:00:00+00:00"}
    assert cov["validate"]["closes"] == 547
    assert snap["bars_content_sha256"] != snap["content_sha256"]
    bars = {s["bar_type"]: cat.load_bars(s["instrument"], s["bar"], catalog_dir=catalog) for s in snap["series"]}
    assert b.content_hash(bars) == snap["bars_content_sha256"] == b.content_hash(bars, {})
    tables = {e["path"]: ext.read_table(catalog, e["symbol"], e["table"]) for e in snap["external"]}
    assert b.content_hash(bars, tables) == snap["content_sha256"]


def test_build_positioning_loads_point_in_time(built, fworld):
    root, _, _ = built
    catalog = root / "data" / "catalog"
    got = ext.load_positioning("BTCUSDT", catalog_dir=catalog)
    assert got.index[0] == pd.Timestamp("2024-05-02", tz="UTC") and got.index[-1] == ext.holdout_cut()
    last = got.iloc[-1]
    assert last["oi_last"] == 80000 + 286 * 3.25  # the row stamped 23:50 on 2024-06-30
    assert last["funding_count_1d"] == 3 and np.isfinite(last["funding_mean_1d"])
    assert np.isnan(got.loc[pd.Timestamp("2024-06-27", tz="UTC"), "oi_last"])  # metrics start that day
    assert got.loc[pd.Timestamp("2024-06-28", tz="UTC"), "oi_last"] == 80000 + 286 * 3.25
    eth = ext.load_positioning("ETHUSDT", "1h", start="2024-06-29 23:00", end="2024-06-30 01:00", catalog_dir=catalog)
    # 2024-06-29 was never published: nothing to show and nothing filled until the 2024-06-30 rows are known
    assert eth["oi_last"].isna().tolist() == [True, True, False] and eth["oi_last"].iloc[-1] == 80000 + 10 * 3.25


def test_build_reports(built):
    root, result, _ = built
    main = Path(result["report"]).read_text()
    assert "### binance_futures" in main and "Up to 2024-06-30 (the validate window's last day)" in main
    assert "Content SHA-256 (bars and positioning tables)" in main
    text = Path(result["positioning_report"]).read_text()
    assert Path(result["positioning_report"]).name == "2024-07-20-positioning.md"
    assert text.startswith(f"# Positioning data report, snapshot `{result['snapshot_id']}`")
    for heading in ["## 1. Files", "## 2. Stored series", "## 3. When a value is known", "## 4. Loading and cleaning",
                    "## 5. Gaps and values", "## 6. Open items"]:
        assert heading in text
    assert "| BTCUSDT | 2024-06-29 | 2024-06-30 | 2 | period starting at T | price at T+5 min | T+5 min |" in text
    assert "| ETHUSDT metrics | 2024-06-28 | 2024-06-30 | 3 | 2024-06-27: not published (404) |" in text
    assert "Missing: ETHUSDT-metrics-2024-06-29" in text and "checked in this build" in text
    assert f"`{Path(result['report']).name}`" in text


def test_offline_rebuild_is_unchanged(built, monkeypatch):
    root, result, _ = built
    monkeypatch.setattr(src, "FUTURES_FIRST", FIRST)
    again = b.build(cfg_for(root, sources=("kraken", "binance_futures"), offline=True), now=NOW)
    assert again["publish"] == "unchanged" and again["snapshot_id"] == result["snapshot_id"]
    assert again["checks"] == result["checks"]  # the online snapshot (with its start checks) is kept as it was


def test_build_without_complete_files_stops(fworld, kworld, tmp_path, first):
    early = datetime(2024, 6, 29, 12, tzinfo=UTC)  # June not over: no 5-minute klines to check the metrics with
    server = Server({**kworld.routes, **fworld.routes})
    with server.client() as c, pytest.raises(b.DataQualityError, match="BTCUSDT: no klines_5m files"):
        b.build(cfg_for(tmp_path, sources=("kraken", "binance_futures"), coins=("BTC",)), client=c, now=early)


def test_metrics_that_reach_past_the_lag_stop_the_build():
    e = b.External("BTCUSDT", pd.DataFrame(), pd.DataFrame(), {}, {"max_reach_minutes": 10, "runs": ["r"]})
    with pytest.raises(b.DataQualityError, match="up to 10 minutes after their create_time, more than the 5-minute"):
        b.check_external([e])


def test_positioning_round_trip_mismatch_stops_the_build(fworld, kworld, tmp_path, monkeypatch, first):
    real = ext.read_table

    def changed(*a, **k):
        got = real(*a, **k)
        got.iloc[0, 2] += 1e-12
        return got

    monkeypatch.setattr(ext, "read_table", changed)
    server = Server({**kworld.routes, **fworld.routes})
    with server.client() as c, pytest.raises(RuntimeError, match="funding.parquet: round trip differs"):
        b.build(cfg_for(tmp_path, sources=("kraken", "binance_futures"), coins=("BTC",)), client=c, now=NOW)
    assert not (tmp_path / "data" / "catalog").exists()


def test_parse_args_positioning():
    cfg = b.parse_args(["--sources", "kraken,binance_futures"])
    assert cfg.sources == ("kraken", "binance_futures")
    assert b.parse_args([]).sources == ("kraken", "binance", "coinbase")  # the default is unchanged


def test_positioning_needs_a_bar_source(capsys):
    with pytest.raises(SystemExit):
        b.parse_args(["--sources", "binance_futures"])
    assert "--sources needs at least one bar source" in capsys.readouterr().err


def test_main_prints_positioning(built, capsys):
    root, result, _ = built
    mp = pytest.MonkeyPatch()
    mp.setattr(src, "FUTURES_FIRST", FIRST)
    try:
        assert b.main(["--offline", "--sources", "kraken,binance_futures", "--data-dir", str(root / "data"),
                       "--report-dir", str(root / "main-reports")]) == 0
    finally:
        mp.undo()
    out = capsys.readouterr().out
    assert "BTCUSDT metrics" in out and "1151 rows" in out and "positioning report: " in out


# ============================================================================ reports


def test_report_path_never_overwrites_another_snapshots_report(tmp_path):
    snap = {"created": "2024-07-20T12:00:00Z", "snapshot_id": "aaaaaaaaaaaaaaaa"}
    assert rep.report_path(tmp_path, snap) == tmp_path / "2024-07-20.md"
    (tmp_path / "2024-07-20.md").write_text("# Data quality report, snapshot `aaaaaaaaaaaaaaaa`\n")
    assert rep.report_path(tmp_path, snap) == tmp_path / "2024-07-20.md"  # its own report: rewritten
    other = {**snap, "snapshot_id": "bbbbbbbbbbbbbbbb"}
    assert rep.report_path(tmp_path, other) == tmp_path / "2024-07-20-bbbbbbbbbbbbbbbb.md"
    assert rep.report_path(tmp_path, other, "-positioning") == tmp_path / "2024-07-20-positioning.md"


def test_a_second_snapshot_on_the_same_day_keeps_the_first_report(kworld, tmp_path):
    """Regression: the report was named by date only, so a second snapshot built the same day overwrote the
    first snapshot's report."""
    with kworld.server().client() as c:
        one = b.build(cfg_for(tmp_path, sources=("kraken",), coins=("BTC",), intervals=("1d",)), client=c, now=NOW)
    before = Path(one["report"]).read_text()
    with kworld.server().client() as c:
        two = b.build(cfg_for(tmp_path, sources=("kraken",), coins=("ETH",), intervals=("1d",)), client=c, now=NOW)
    assert two["snapshot_id"] != one["snapshot_id"] and Path(one["report"]).name == "2024-07-20.md"
    assert Path(two["report"]).name == f"2024-07-20-{two['snapshot_id']}.md"
    assert Path(one["report"]).read_text() == before


def test_positioning_report_optional_branches(built):
    root, result, _ = built
    snap = json.loads((root / "data" / "catalog" / cat.SNAPSHOT_FILE).read_text())
    snap["sources"]["binance_futures"]["details"]["starts"] = "not checked (offline build)"
    snap["sources"]["binance_futures"]["details"]["periods"]["ETHUSDT klines_5m"] = None
    snap["checks"]["metrics_timing"]["BTCUSDT"]["runs"] = [
        {"from": "2024-06-27", "to": "2024-06-27", "days": 1, "taker_offset": 5, "price_offset": -5},
        {"from": "2024-06-28", "to": "2024-06-28", "days": 1, "taker_offset": None, "price_offset": None},
    ]
    snap["checks"]["external"]["BTCUSDT metrics"]["open_interest_longest_unchanged"] = None
    fields = snap["checks"]["external"]["BTCUSDT metrics"]["fields"]
    fields["open_interest"]["longest_absence"] = None
    text = rep.render_positioning_report(snap)
    assert "| ETHUSDT klines_5m | none | none | 0 | n/a |" in text
    assert "Start check: not checked (offline build)." in text and "not re-checked in this offline build" in text
    assert "| BTCUSDT | 2024-06-27 | 2024-06-27 | 1 | period starting at T+5 min | price at T-5 min | T+10 min |" in text
    assert "| BTCUSDT | 2024-06-28 | 2024-06-28 | 1 | inconclusive | inconclusive | n/a |" in text
    assert "| BTCUSDT | open_interest |" in text and "| none |" in text
    assert "Longest unchanged open interest left after the stale rule: none" in text
    assert "Bars of this snapshot and their checks: the data quality report of this snapshot" in text
    assert "| ETHUSDT | train | 2191 |" in text and "| 0 |" in text
