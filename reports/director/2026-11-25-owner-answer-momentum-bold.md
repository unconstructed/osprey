# Owner decisions for the momentum-bold study (2026-11-25, in chat)

Asked as multiple-choice prompts before any plan, code or data for the study existed. No market data for it had been
read. Each answer was the recommended option.

1. **Next study:** "Momentum, many coins": the `momentum-bold` strategy of AGENTS.md (each week hold the top few coins
   by trailing return from a wider list, the rest in USDC), chosen over the NautilusTrader runner, measuring Base costs
   and a funding-rate filter. Context given: six studies of timing rules on BTC and ETH found no return edge.
2. **Coin pool:** "Top 20 by volume, then": at each date, the 20 most-traded coins on Binance at that time, including
   coins later delisted or collapsed (no survivorship bias). Production would later trade only vetted coins on Base.
3. **Bold's drawdown budget:** **60%** (the Monte Carlo 95th-percentile max drawdown). Written into
   `config/risk_levels.yaml`.
4. **Costs of coins other than BTC and ETH:** **2x** the BTC/ETH placeholder pool fee and slippage (gas unchanged), on
   top of the existing placeholders, before the 2x stress rerun. Written into `config/costs.yaml` as
   `small_coin_cost_multiplier: 2.0`.
5. **Process:** the owner asked to keep token use low: one short plan, one builder, no separate code-review round,
   one audit after the run.
6. **The coin list's host** (asked after the data agent found that data.binance.vision cannot list its own files):
   "Allow the listing host (Recommended)". `s3-ap-northeast-1.amazonaws.com` may be used for read-only S3 ListObjects
   on bucket `data.binance.vision`, prefix `data/spot/monthly/klines/`, to list Binance spot symbols, delisted ones
   included. Every price file and checksum still comes from data.binance.vision. Not chosen: a hand-made list (risks
   missing delisted coins) and pausing the study.
