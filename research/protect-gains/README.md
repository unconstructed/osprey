# protect-gains

A "protect my gains" brake for customers of the "hold this mix" tool: when the wallet falls too far it sells to USDC,
and later buys the mix back. Two kinds of line are offered:

- **A:** sell if the wallet falls X% below its highest value.
- **B:** keep at least Y% of the profit.

Two kinds of buy-back are offered as well: automatic (when the market turns up) or wait for the customer. The
simulation picks the starting setting of each by rules fixed in advance. It is a safety brake, not a money-maker:
the study claims no edge.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-23, the small version): reviewed by `backtest-auditor` and
  `risk-officer` with no market data, with the owner's answers (a 'back to where we sold' buy-back; line B starts later;
  the simulation compares both readings of the tool's trade limit). Next: the full test tiers, then run 0.
- Status 2026-11-23: plan committed; code and tests built (`lab/runner/protect.py`, `run.py`, `tests/test_protect.py`,
  `tests/test_protect_run.py`); amendments A1 (timing, 95.1 CPU-minutes) and A2 (readings) recorded. No run yet. Validate-window looks used: 0. The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.
