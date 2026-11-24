# vol-steady

A volatility-scaled hold for the Steady level: hold BTC and ETH half and half up to the customer's crypto share, and
step back in quarters when crypto has been wilder than a target level. The owner asked for it on 2026-11-23 as the
next hunt for a real edge.

- Plan: [PLAN.md](PLAN.md), the pre-registration (2026-11-23). It reuses trend-steady's reviewed protocol (the folds,
  the luck checks, the gates, the verdict and the one validate look) and changes only the rule.
- Status 2026-11-24: **run 0 done, verdict NO EDGE** ([RESULTS.md](RESULTS.md)). Over 2018-2022 the rule made +210%
  (worst fall 47%), against +170% (44%) for holding the same mix: a small lead that could be luck (p 0.25). Its timing
  beat shifted copies with one search seed but not the other, and holding its own average mix did better. After
  2018 the search chose to step back only in extreme spells. No validate look (validate-window looks used: 0); the
  test window is never read.
- Every number it will produce is SCOUTING (the reference engine, placeholder costs), not NautilusTrader.
