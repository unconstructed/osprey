# protect-gains

A "protect my gains" brake for customers of the "hold this mix" tool: when the wallet falls too far it sells to USDC,
and later buys the mix back. Two kinds of line are offered:

- **A:** sell if the wallet falls X% below its highest value.
- **B:** keep at least Y% of the profit.

Two kinds of buy-back are offered as well: automatic (when the market turns up) or wait for the customer. The
simulation picks the starting setting of each by rules fixed in advance. It is a safety brake, not a money-maker:
the study claims no edge.

- Plan: [PLAN.md](PLAN.md), a DRAFT written 2026-11-23 before any code or result. Next: the `backtest-auditor` and
  `risk-officer` review, the owner's answers to section 15, then the commit as the pre-registration.
- Status 2026-11-23: plan only. No code, no run. Validate-window looks used: 0. The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.
