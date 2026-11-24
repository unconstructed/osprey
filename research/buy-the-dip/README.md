# buy-the-dip

The owner's dip ladder, a self-directed template for the app: "when crypto falls Y% from its recent high, buy crypto
with X% of my cash, and buy another X% at each further fall of Z%, until at most M% of my cash is used". The study
picks a suggested starting setting of X, Y, Z and M by rules fixed in advance, and measures how it compares with
spreading the same money monthly and with buying it at once. It claims no edge.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-24), modelled on protect-gains' plan.
- Status 2026-11-24: plan committed, with amendment R1 (`risk-officer` confirmed the allowed range and tightened the
  caps rule). No code, no run.
  Validate-window looks used: 0 (none planned). The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.
