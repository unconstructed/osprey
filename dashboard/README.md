# Results dashboard

`index.html` is one self-contained page showing the state of the Strategy Lab:
milestones, strategies and their audits, test health, data, search runs and
reports. Open it in a browser from your clone; it works from `file://` with no
network. GitHub shows the HTML source, not the page.

It is generated. Don't edit `index.html` by hand: edit `status.json` (the only
hand-typed input) or the files it reads, then rebuild and commit both.

## Rebuild

From the repo root:

```bash
python3 scripts/build_dashboard.py                 # read the repo, write dashboard/index.html
python3 scripts/build_dashboard.py --json PATH     # also write the collected data as JSON
python3 scripts/build_dashboard.py --sample --out /tmp/sample.html   # synthetic preview
```

`--root PATH` reads another checkout and `--out PATH` writes elsewhere. The
builder uses the Python standard library only and prints a one-line summary.
A missing input shows an empty state with a hint; a broken one shows up under
Warnings. It never stops the build.

`--sample` builds from a synthetic repo tree made at run time in the system temp
folder (fixed seed 7) and deleted after the build. The page carries a sticky
"SAMPLE DATA - not real results" banner, its title starts with "SAMPLE", and each
strategy card and chart is marked SAMPLE. It refuses an `--out` inside a git
checkout. Never commit a sample page.

## What each section shows

| Section | Shows | Reads |
|---|---|---|
| Header | Build time (UTC), git commit and branch, data snapshot id, the `status.json` note, integrity warnings | git, `data/catalog/SNAPSHOT.json`, `dashboard/status.json` |
| Overview | Milestones done, strategies ready for paper / audited / tracked, latest test run, coverage, warning count | Everything below |
| Milestones | Milestones 0-5 with done-when text, status and note | `AGENTS.md` `## Milestones`, `status.json` |
| Strategies | One card per strategy: lifecycle stage, latest audit state, the nine gates as recorded, equity vs benchmarks (normalised to 1.0, log or linear, with a data table), metrics vs benchmarks, audit details, history, paper and export status | `AGENTS.md` launch table, `strategies/<name>/`, `reports/<name>/<YYYY-MM-DD>.json`, `exports/<name>/config.yaml`, `status.json` |
| Gate matrix | Latest audit per strategy against each gate: pass, fail, pending or missing | Audit JSON |
| Testing health | Latest run counts, coverage and lowest-covered files, mutation score per area vs target, definition of done, bug-log count, open work 5.1-5.7 | `results/tests/` (git-ignored), `TESTING.md`, `status.json` |
| Data | Snapshot summary and series, data-quality reports | `data/catalog/SNAPSHOT.json` (git-ignored), `reports/data/*.md` |
| Search runs | Folders under `results/` except `tests/`: Parquet file count, Optuna journal, last modified | `results/` (git-ignored, local only) |
| Reports | Every `reports/**/*.md`, newest first | `reports/` |
| Warnings | Every file the builder could not read, or that does not add up | - |

How a strategy's state is derived: any gate `pass: false` gives FAIL; all nine
`true` gives READY FOR PAPER; eight `true` with `final_test` pending gives
AWAITING FINAL TEST; anything else, including a missing gate, gives INCOMPLETE.
If the newest dated audit file can't be read, the strategy shows UNREADABLE:
an older audit never stands in for it.
Values are never re-judged against thresholds. If an audit file's `verdict` says
PASS but its flags do not, the page shows an integrity warning.

Pass, fail and status are always shown with an icon and a word, never by colour
alone. The page follows the system's light or dark setting.

## Input reference

Every input, the exact commands that produce the test, coverage and mutation
files, the `status.json` format and the audit JSON schema (`osprey.audit/1`) are
in [HOWTO.md: Dashboard](../HOWTO.md#dashboard).

## Files

| File | What it is |
|---|---|
| `index.html` | Generated page (committed so it opens directly) |
| `template.html` | Page template: layout, styles and the vanilla-JS renderer. Data is injected by the builder |
| `status.json` | Hand-kept status: milestones, open work, paper accounts |
| `../scripts/build_dashboard.py` | The builder |
| `../tests/test_dashboard.py` | Its tests (standard library + pytest): `uv run pytest tests/test_dashboard.py`. They run with the rest of `tests/` in the quick, full and deep tiers. Inside mutmut's `mutants/` copy of `tests/` they find the builder by walking up to the repo root, and skip if there is none |
