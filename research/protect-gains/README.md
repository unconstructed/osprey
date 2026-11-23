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
  the simulation compares both readings of the tool's trade limit). Next: one audit.
- Status 2026-11-23: run 0 done on the train window ([RESULTS.md](RESULTS.md)). **No starting setting for either line**:
  line A at 10% with the trend buy-back was the only setting that cut the bad-case fall enough for every mix (90th
  percentile 26% against 65%), but 36% of its buy-backs were sold again within a month (the plan allows 25%), and it
  cost a median 23% over two years. The owner decides (RESULTS.md, "For the owner"). Validate-window looks used: 0. Validate-window looks used: 0. The test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.
