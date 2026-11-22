# Technical

[← Hub](README.md) · [Features](features.md) · [Product](product.md) · [Business](business.md)

## Architecture

```
iOS / Android app (React Native + Expo)
    │ HTTPS + push                 │ Privy SDK: login, Face ID passkey,
    │                              │ user signs approvals on the phone
    ▼                              ▼
Load balancer + WAF            Privy (wallet provider)
    │                          user-owned wallets on Base;
    ▼                          enforces auto-trading permissions
App API (FastAPI) ── portfolio, rules, approvals, limits, permissions, notifications
    │
    │        NautilusTrader: THE CHEF
    │        one node per strategy, trading its own paper model account
    │        watches prices → decides "buy BTC"
    │            │
    │            │ signal (Redis stream)
    ▼            ▼
Trade router: THE WAITER (our own Python service)
    finds subscribers and triggered rules, sizes each trade to the user's
    balance and limits, runs risk checks, builds the swap with price protection
    │
    ├── Auto-trade: signs inside the user's permission (Privy signer)
    └── Approve: push → user confirms with Face ID on their phone
    │
    ▼
Base: swap through the 0x aggregator (decentralized exchanges)
    │
    ▼
Chain watcher: confirms trades, reads balances, reconciliation

Ramps: Coinbase Onramp/Offramp, MoonPay (cash in and out, ID checks for those)
Data: PostgreSQL · Redis · SQS · S3 (Object Lock)
```

**We never hold customer funds.** Every user owns their wallet. Our servers can only make the trades a user's auto-trading permission allows, and can never send money out of a wallet.

### Who does what: Nautilus vs. the trade router

**Nautilus is the chef:** it decides *what* to trade, once per strategy. **The trade router is the waiter:** it delivers that decision to *each user*, in their size and within their limits. Nautilus never touches a user's wallet.

| | NautilusTrader (chef) | Trade router (waiter) |
|---|---|---|
| Runs as | One node per strategy | One service for all users |
| Knows about | Prices and its own strategy | Users, subscriptions, modes, limits, permissions, approvals |
| Decides | What to trade, and when\* | How much for each user, and whether it's allowed |
| Trades | Its own paper model account only | Every user's wallet: inside their permission (Auto) or with their signature (Approve) |
| Sends out | One signal per decision | One swap per user |

\* *Proposed exception, needs an owner decision:* for customers off a strategy's default settings, trade timing would be decided outside Nautilus by code that must pass a decision-parity test against the Nautilus strategy. See [Strategy settings](#strategy-settings).

**Why:** Nautilus is built to trade one account through one connection, not thousands of user wallets. Keeping user trades in our own code means every money path is code we write and test directly.

### The model account

- Every strategy node trades a paper (simulated) account on live prices, as if it were one user with a standard allocation.
- That gives each strategy a clean live track record for its strategy card, kept separate from backtests.
- Prices come from exchange feeds (Nautilus's Coinbase or Kraken connector). Actual swap prices on Base can differ slightly, so each user's own results come from their real on-chain trades, shown in their portfolio.

### The signal

What Nautilus sends the trade router for every decision:

| Field | Example | Used for |
|---|---|---|
| Signal ID | unique per decision | Never acting on the same signal twice |
| Strategy | `dip-buy-btc` | Finding subscribed users |
| Coin and direction | BTC, buy | The swap |
| Target | hold 25% of the strategy's allocation in BTC | Sizing: the router works out each user's amount from their own allocation and current on-chain holdings |
| Reason | "BTC dropped 6% today" | The "why did this trade happen" line and the notification |
| Price at decision | last price Nautilus saw | Dropping the trade if the swap quote has moved too far since |
| Created / expires | timestamps | Dropping late signals; the approval window |

### Strategy settings

Customers can change a strategy's settings inside the approved range (tested by the lab, approved by the owner). See [Features: Adjustable strategy settings](features.md#adjustable-strategy-settings).

**Where the ranges come from.** Each approved strategy's export from the lab lists:
- every setting, with its default and its allowed values (the steps the controls move in);
- the risk level's limits;
- the backtested worst fall at each combination of settings.

The app loads the export read-only. Only the owner approves a new or wider range. *(The lab side is in AGENTS.md since 2026-11-20, owner: "yes to 1"; see [reports/director/2026-11-20-adjustable-settings.md](../../reports/director/2026-11-20-adjustable-settings.md).)*

**What's stored.** One small versioned record per subscription: the chosen value for each setting, the customer's loss limit, and the export version they were checked against. Editing creates a new version, and every trade records the version it used, as with rule records.

**Validation.** On save:
- every value must be one of that setting's approved values, so the combination is one the lab tested;
- the targets must sit inside the level's limits, with the lab's margin;
- the loss limit must be tighter than the level's drawdown budget.

Anything else is refused, with no override. The risk engine checks again before each trade and fails closed.

**Who decides what (proposed; needs an owner decision).** The strategy's Nautilus node runs the default settings on its model account, and that is the strategy's live record. For a customer on other settings, the decisions would follow that customer's own wallet:
- the crypto share and split set that customer's targets;
- the drift band and check frequency decide when their wallet is brought back to target, from their on-chain holdings.

For customers off the defaults, this departs from "NautilusTrader is the only engine": their trade timing would be decided by code outside Nautilus, which must pass a decision-parity test against the Nautilus strategy. "When to trade" would then be decided per customer, like a customer rule, and the chef/waiter split above bends. Nautilus would still run once per strategy, never once per customer. The alternatives keep Nautilus as the only decision-maker: fixed settings at launch, or one Nautilus node per approved combination.

The timing question also reaches customers on the defaults. A wallet that joined, or added cash, after the model account's last rebalance drifts from different weights, so a band breach on the model account is not that wallet's breach. If those customers simply follow the model account's signals, they are rebalanced on its schedule, not their own, and that differs from the backtest of their own book. The owner's decision above should cover them too.

**Worst fall shown.** The app shows the export's backtested numbers for the chosen combination, labeled hypothetical. Unlike rule backtests, nothing is backtested on our servers for strategy settings.

**"Hold this mix" is not a strategy setting.** It is a self-directed tool, not one of our strategies (owner, 2026-11-20; see [Features: Hold this mix](features.md#hold-this-mix)). The customer's mix has no approved range, no export, no Nautilus node and no model account. Like a customer rule:
- it is checked per customer, against that customer's own on-chain holdings, so the per-customer timing question above, which is about our strategies, does not arise for it;
- its trades go to the trade router with the same sizing and risk checks, in the customer's chosen mode (Auto-trade or Approve; owner, 2026-11-20);
- its record (mix, drift band, reset schedule, mode) is versioned, and every trade records the version it used;
- Steady's "a few trades a month" caps its drift band (owner, 2026-11-20). The customer sets the number, and the app recommends one based on the lab's data and simulations (owner, 2026-11-20). The lab's simulation (SCOUTING: reference engine, placeholder costs, 2017-2022 data only; [RESULTS.md](../../research/hold-mix-cap/RESULTS.md)) gives a default drift band of 50% of each coin's target with a cap of 1 rebalance a month, and a recommended cap for each band ([Features: The recommended cap and drift band](features.md#the-recommended-cap-and-drift-band); since 2026-11-22 only the 30% and 50% bands are offered, below), to be rechecked with measured Base costs before the app shows it. The default is the same for every customer, with no default per wallet size (owner, 2026-11-22; the owner is asked to confirm it, because the question's premise was not what the study found: [record](../../reports/director/2026-11-22-owner-answers-hold-mix.md), item (h)). The app enforces the cap as a minimum wait of 30/N days (rounded up) between rebalances, checked once a day; the first buy that sets up the mix neither counts nor starts the wait; resets count; a Steady limit hit is fixed at the next daily check even inside the wait and counts (decided by the lab; owner, 2026-11-21: "you decide"; [Features: Hold this mix](features.md#hold-this-mix));
- **Steady's hard limit for this tool: at most 2 rebalances in any 30 days** (owner, 2026-11-22; [record](../../reports/director/2026-11-22-owner-answers-hold-mix.md); [Features: Steady's trade limit for this tool](features.md#steadys-trade-limit-for-this-tool)).
  - The rule engine and trade router read it from Steady's entry in `config/risk_levels.yaml` (`hold_mix_max_rebalances_per_30d: 2`), never from a number in code. From it they derive the shortest wait, ceil(30 / value) days (15 at 2), which counts band and reset trades.
  - On save, the customer's cap must be at most that number, and the band one of the two the app offers under it: 30% or 50% of each coin's target (the owner: no band tighter than 30%; these two bands: the lab's reading). Anything else is refused.
  - Limit fixes are exempt from it, as from the customer's own cap: neither the wait nor the limit holds them back, so they go through at the next daily check, even inside the wait. They are not among the 2, but they restart the wait. A pause, or a trade on Approve that is not approved, still holds them; whether a sell-only fix may go through during a pause is open.
  - The limit applies to this tool only, not to our Steady strategies (owner, 2026-11-22: "Only the hold-this-mix tool"). Their settings are validated against their approved range, as above;
- **The mix's risk label** (owner, 2026-11-22). Any mix is allowed (owner); the lab reads this as: any mix the Steady limits allow can be saved. The app shows it under Balanced or Bold, not Steady, when its hypothetical past worst fall is more than Steady's budget of 35%. *Proposed:* the app reads the budget from `max_drawdown_budget_pct` in the same file, never from a number in code. *Open* ([Features: The risk label of a mix](features.md#the-risk-label-of-a-mix)):
  - which worst-fall number decides it;
  - where Balanced ends and Bold begins (both budgets TBD);
  - what Balanced's required stop-loss means for the tool;
  - Bold's empty coin list;
  - whether the tool's mechanics stay the same under those labels;
- *Proposed by `risk-officer`, for the app team ([RISK.md](../../research/hold-mix-cap/RISK.md) section 6):* a trade back to the mix that brings the wallet back inside Steady's limits is never held back by the wait or by the limit of 2 rebalances in any 30 days (for the limit, decided: owner, 2026-11-22); if the router refuses one, the app sends the "limit hit" push, retries at the next daily check, and alerts if a wallet stays past a limit for more than one check. The auto-trading permission's amount caps must allow a full trade back to the customer's mix: in 2017-2022 that took up to 56% of the wallet in one swap and 62% in one day, and the first buy up to 78% in one day (the largest seen, not bounds). With fixed percentages that means at least 60% per swap and 80% per day, and a larger trade goes to the customer for approval, never silently dropped. Sell legs go before buy legs, and the limits are checked after the whole trade. The app's rule must make the same decisions as the lab's `lab/runner/holdmix.py`, pinned by a decision-parity test;
- the customer's daily or weekly loss limit pauses it, as it pauses their strategies and their own rules (owner, 2026-11-20; rules 2026-11-21), and Pause everything stops it. A pause stops its trades and sells nothing.

Its worst fall is a Nautilus backtest on past prices with swap fees, slippage and gas included, labeled hypothetical, as rule backtests are. If the controls move in steps (proposed), every mix, drift band and reset schedule can be backtested ahead of time, not on demand. The lab doesn't test or approve any mix; the number describes the past only. *Open:* which years these backtests cover. The tool runs the same kind of rule as the lab's rebalance-steady study. The lab's validate data (2023-01-01 to 2024-06-30) are unlooked for that study, and its test data (from 2024-07-01) are opened once per strategy (AGENTS.md "Splits"; hard rule 5). Worst falls over those years, if the desk can see them, would spend those windows for any later Steady rebalancing strategy of ours. Agree the years with `backtest-auditor` before any of these backtests is run.

These backtests need a Nautilus rebalancing backtest with the lab's cost model. Both wait on the lab's milestone 2 (the Nautilus runner and the fee and fill models), and the costs are placeholders until measured. Rule backtests on our servers only arrive in Phase 2, so for a Phase 1 launch the table is computed ahead of time; who computes it is not decided yet. As with rules, the live check and the backtests should use the same rebalancing logic, so a mix behaves the same in both.

*Open:* the owner's decision above. If the per-customer check is accepted, does it run in the rules service or in the trade router? Before production, AGENTS.md now requires at least 4 weeks on paper model accounts at the default and at the riskiest combination in the approved range. It doesn't say whether the second account keeps running afterwards for the live record. The owner can still drop that second account (director report, decision 2).

### Customer rules and advanced mode

Customers build their own strategies as **rules stored as data, never as code**. One shared rule engine runs every customer's rules, the way one machine program runs many recipes.

**Two modes, same kind of record**
- **Simple mode (Phase 1):** templates like "buy $X when BTC drops Y%"
- **Advanced mode (Phase 2, paid tier):** more building blocks (moving averages, RSI, price change, AND/OR conditions, several coins, take-profit and stop-loss, schedules) plus a **Backtest** button. The AI copilot writes these same records from plain English.

**What's stored:** one small, versioned record per rule in Postgres (protected by Row-Level Security like all customer data):

```json
{
  "rule_id": "r_8f3k",
  "user_id": "u_1042",
  "version": 3,
  "coin": "ETH",
  "when": { "all": [
    { "indicator": "price_change", "period": "7d", "below": -10 },
    { "indicator": "rsi", "period": 14, "below": 30 }
  ]},
  "action": { "side": "buy", "amount_usd": 200 },
  "stop_loss_pct": 8,
  "take_profit_pct": 15,
  "max_runs_per_week": 1,
  "mode": "auto",
  "status": "active"
}
```

**Validation:** every rule is checked against a fixed schema before it's saved: only allowed building blocks, stop-loss required, coins within the user's risk level, sizes within the user's limits. No customer code is ever stored or run.

**Live evaluation (rules service)**
- On each new price for a coin, each indicator is calculated **once**, then every rule on that coin is checked against those shared numbers. 5,000 "RSI under 30" rules still means one RSI calculation, so the engine stays cheap as users grow.
- A triggered rule goes to the trade router as a signal, with the same sizing and risk checks as a strategy signal, and executes in the rule's mode (Auto or Approve). Its reason line is generated from the rule ("ETH down 10% this week and RSI under 30").
- Limits: a cap on active rules per user, a minimum time between checks (no rapid-fire, fee-burning bots), and each rule's own run cap.

**Backtests**
- One shared Nautilus `RuleStrategy` reads a rule record as its settings. **Backtest** runs it on past prices as a short job on our servers, with swap fees, slippage and gas included. Only the results are saved, labeled hypothetical.
- Live evaluation and backtests use the same rule-evaluation library, so a rule behaves the same in both.

**Versioning:** editing a rule creates a new version. Every trade records which rule version fired it, for "why did this trade happen" and the audit log.

### If something breaks

- **Nautilus node goes down:** no new signals, so nothing trades for that strategy; alert fires
- **Signal arrives late, or the swap quote has moved too far from the signal price:** the router drops it
- **Same signal arrives twice:** ignored (signal ID)
- **Swap fails on-chain:** retried only inside the signal's time window, never late; then logged and the user notified
- **Wallet provider (Privy) outage:** auto-trades stop and approvals wait; nothing executes outside a permission
- **Kill switch:** stops all trades in the router immediately, even if Nautilus keeps sending signals; all auto-trading permissions can be revoked in bulk

### Components

**Trade router**
- Fan-out from one signal to many user trades
- Per-user trades go through an **SQS queue**, so a burst (one signal × every subscriber, or a volatile market) never overwhelms the API, the swap aggregator's rate limits or the wallet provider; failed trades land in a dead-letter queue for review, never a silent retry
- Per-user sizing from the user's allocation and **on-chain balance**, then limit checks
- Builds each swap through the **0x Swap API** with a minimum-received amount (price protection) from the signal price and the user's slippage limit
- **Auto mode:** signs through the user's permission (see [Auto-trading permission](#auto-trading-permission)). **Approve mode:** creates a pending approval and sends the push; expired approvals are dropped
- Idempotent: one trade per signal per user, enforced by a unique key in Postgres, so a retry can never double-buy

**Risk engine (four layers)**
- *Platform:* global kill switch, max total trading volume, rate limits, stale-price guard
- *Strategy and risk level:* auto-halt a strategy whose live results leave its risk level's range; enforce each level's guardrails (allowed coins, max per coin, cash floor)
- *User:* their strategy settings (approved values only), personal limits, loss limit auto-pause, Pause everything
- *Wallet permission (hard backstop):* the wallet provider refuses anything outside the user's permission, even if every layer above has a bug
- Fails closed: any error inside a risk check rejects the trade

**Chain watcher and reconciliation**
- Watches every submitted swap until confirmed; reads balances directly from Base
- On a schedule, compares our records of each user's trades and balances with the chain
- On mismatch: pause auto-trading for the affected users and alert; never guess
- The blockchain is the source of truth for balances; our ledger mirrors it

**Ramps integration**
- Coinbase Onramp/Offramp: backend creates a single-use session token per user session; status by webhook and status API
- MoonPay: signed widget URLs for buy and sell; status by webhook
- Cash-out sends USDC from the user's wallet to the ramp partner's deposit address; in the app this is always a Face ID-confirmed send by the user, never an auto-trade

**Ledger and audit log**
- Every signal, approval, permission grant and revoke, trade (with transaction hash) and cash in/out recorded, append-only
- Source for customer history, tax exports and investigations
- Regular exports archived to S3 with Object Lock so they can't be altered or deleted

**Auth**
- Privy handles login (email, Apple, Google) and the Face ID passkey; the app API verifies Privy tokens
- ID checks happen only inside ramp partners' flows when buying or cashing out

**Notifications service**
- Push (APNs / FCM via Expo), in-app inbox, email for monthly statements

**Admin dashboard**
- User lookup, strategy health, halt a strategy, revoke a user's permissions, incident handling

**Monitoring and alerting**
- Price feed outages, failed swaps, queue backlogs, reconciliation mismatches, unusual losses, gas spend, permission expiries, wallet provider and RPC outages → paging alerts

## Launch chain and trading

| Piece | Choice | Why |
|---|---|---|
| Chain | **Base** (Coinbase's Ethereum layer 2) | Low fees; native USDC; deep liquidity for BTC (cbBTC) and ETH against USDC; supported by Coinbase's ramps, Privy and 0x |
| Cash | **USDC** (native on Base) | Shown in the app as a dollar balance; what ramps buy and sell |
| Bitcoin | **cbBTC** (Coinbase Wrapped BTC) | Backed 1:1 by bitcoin held by Coinbase; a trust layer we disclose to users |
| Swaps | **0x Swap API** | Aggregates Uniswap and other decentralized exchanges for the best route; the same engine behind Coinbase's developer Trade API |
| Network fees | **Sponsored** through Privy's gas sponsorship | Users never need ETH for fees; cost tracked per trade and covered by subscriptions |
| Testing | **Base Sepolia** testnet | Dev and staging run on testnet with no real money |
| Blockchain access | Managed RPC provider (for example Alchemy) | No nodes of our own to run |

**Coin allowlist:** each risk level has a list of allowed tokens, limited to tokens with deep liquidity on Base. The list is reviewed monthly and is copied into every auto-trading permission.

## Wallets and login

- **Privy** (Expo SDK): login with email, Apple or Google; a wallet is created automatically at sign-up
- **Face ID passkey, no seed phrase;** recovery through Privy's recovery options
- **Smart wallets** (ERC-4337) for gas sponsorship and batching (for example, token approval and swap in one step)
- **Users own their wallets.** Keys stay inside Privy's secure enclaves; we never see private keys. Users can export their wallet and take it elsewhere.
- **Turnkey** is the alternative with the same model (keys in secure enclaves, policy engine) if Privy's pricing or terms don't work out
- Privy replaces Cognito: one provider for login and wallets

## Auto-trading permission

**How it works**
1. The user turns on Auto-trade for a strategy, a rule or "hold this mix". The app shows the plain-English permission screen; the user confirms with Face ID.
2. The app adds our server's **authorization key** to the user's wallet as an additional signer, attached to a **policy**. The user stays the wallet's owner.
3. The trade router can now sign swaps while the user is offline, but only what the policy allows. The policy is enforced inside Privy's secure enclave, so a bug or breach in our code still can't go beyond it.

**What the policy allows** (generated per user from their risk level and limits)

| Rule | Setting | Why |
|---|---|---|
| Allowed contracts | The 0x swap contracts (and the token-approval contract they use) only | Only swaps, only through the vetted aggregator |
| Allowed tokens | USDC plus the risk level's coin allowlist | No scam tokens; no coins above the user's level |
| Amount caps | Max per trade and per day, from the user's limits | Caps the damage from any bad signal |
| Destination | The user's own wallet only | Money can never leave the wallet |
| Everything else | Denied: transfers, approvals to other contracts, signer or policy changes | It can't move funds or widen its own permission |
| Expiry | 90 days; the user renews with Face ID | Permissions don't live forever |

*Build note:* confirm which of these checks Privy's policy engine supports natively (contract, calldata and amount conditions). Anything it can't enforce is enforced in the trade router and flagged in the risk register.

**Turning it off**
- Turning off Auto-trade, **Pause everything**, or Account → Auto-trading → Revoke removes the signer immediately
- The admin dashboard and the kill switch can revoke permissions in bulk

**Protecting our signing key**
- The authorization key lives in AWS KMS / Secrets Manager; only the trade router's service role can use it
- Every signing request is logged with user, permission version, signal ID and transaction hash
- Key rotation is planned and rehearsed; a suspected compromise triggers bulk revocation

## Engine

**NautilusTrader is the only engine.** The same strategy code runs in three modes, so nothing is rebuilt between testing and production:

| Mode | What it does | Used for |
|---|---|---|
| **Backtest** | Replays past prices | Proving a strategy idea; backtest numbers on strategy cards (always labeled hypothetical) |
| **Paper** | Live prices, fake money | Each strategy's model account, and weeks of testing before any real money |
| **Live** | Real money | Optional: the owner's own exchange account through Nautilus's Coinbase or Kraken connectors. User trades never run through Nautilus; they go through the trade router |

**Version:** Nautilus v2 (Rust core, strategies written in Python), currently at release-candidate stage; v1 is being retired. Pin an exact version, require Python 3.13+, and read the release notes before every upgrade, because breaking changes ship in normal releases.

**Strategies by risk level:** each strategy is one Nautilus strategy class plus a settings file (coins, sizes, stops, risk level). Launch lineup: rebalancing (Steady), dip buying (Balanced), momentum (Bold); see [Product: Strategies by risk level](product.md#strategies-by-risk-level). New variants are mostly new settings files. Backtests always include swap fees, slippage and gas.

**Research and approval:** strategies are built, mass-simulated and validated in the Strategy Lab at the root of this repo; only approved configs are exported to production: pinned code and data, plus each setting's default and approved range (AGENTS.md "Ready for production", since 2026-11-20; see [Strategy settings](#strategy-settings)). See [Strategy Lab](../../AGENTS.md) and [research methods](../../research-methods.md).

**Not using:** Freqtrade, Jesse and Hummingbot, dropped to keep one engine. No leverage, short selling, market making or arbitrage at any risk level.

Users never see the engine; they see strategies.

## Database

### Multi-tenancy model

This is a consumer (B2C) app, so each customer is a **user**, not a separate tenant. Use **one shared database** with a `user_id` on every customer-owned row, enforced by **Postgres Row-Level Security** so one user's query can never return another's data.

Add an `org_id` tenant layer only if we later white-label the platform for other businesses (B2B2C).

### Data stores

| Store | Holds | Why |
|---|---|---|
| **PostgreSQL** (managed) | Users (keyed to Privy user ID and wallet address), settings, customer rules and "hold this mix" mixes (versioned records), strategy subscriptions, modes and settings (versioned records), auto-trading permissions (policy IDs and versions), signals, approvals, trades (transaction hashes), cash in/out records, audit log | Relational, transactional, Row-Level Security; NautilusTrader also supports Postgres |
| **Ledger tables in Postgres** | Every trade and cash movement, append-only | Never update or delete; corrections are new entries. Mirrors the chain; used for history and taxes |
| **Price history tables in Postgres**, partitioned by date | Price history, candles, strategy performance | AWS's managed Postgres (RDS and Aurora) doesn't offer the TimescaleDB extension, so start with plain date-partitioned tables. Move to Timescale's own cloud or ClickHouse if chart and performance queries slow down |
| **Redis** | Nautilus cache and message bus, the signal stream from Nautilus to the trade router, rate limits, live prices | NautilusTrader uses Redis for crash recovery |
| **Object storage (S3)** | Backtest results, logs, statements, data snapshots; ledger and audit archives under Object Lock | Cheap, durable; Object Lock makes archives tamper-proof |

**What we don't store:** private keys (they stay with the wallet provider), ID documents, bank details and card data (they stay with the ramp partners). Secrets live in Secrets Manager / KMS, never in the database, code or mobile app.

## Hosting

**AWS** recommended: wallet providers, ramp partners and app reviewers will check our security, and AWS has the compliance tooling (encryption keys, audit trails, private networking) they expect.

Start lean and upgrade only when real load calls for it. Anything that protects money or records (Multi-AZ database, queues, tamper-proof logs, key protection) is in from day one.

### Phase 1: Launch

| Piece | Service | Note |
|---|---|---|
| App API, trade router, rules service, chain watcher, workers | Containers on ECS Fargate | No servers to patch |
| Nautilus strategy nodes | Long-running ECS services | Need always-on WebSocket connections; not serverless |
| Login and wallets | **Privy** (external) | Login, passkeys, embedded and smart wallets, signers and policies, gas sponsorship |
| Edge | Load balancer + AWS WAF | Blocks abusive traffic and rate-limits the API |
| Postgres | RDS for PostgreSQL, **Multi-AZ** | Keep a standby in a second availability zone; point-in-time backups |
| Redis | ElastiCache | Required by Nautilus for crash recovery |
| Trade queues | SQS, with dead-letter queues | Absorbs signal fan-out and market spikes; pay per use |
| Secrets and keys | Secrets Manager + **KMS** | Privy app secret and the auto-trading authorization key; API keys for 0x, RPC and ramps |
| Blockchain access | Managed RPC provider | Reads balances and submits transactions on Base |
| Audit archive | S3 Object Lock + CloudTrail | Immutable ledger exports and audit logs |
| Push notifications | Expo push → APNs (iOS) / FCM (Android) | |
| Mobile builds | Expo EAS | See [Product: Release process](product.md#release-process) |
| Marketing site / web checkout | CloudFront + S3 | Also hosts optional web subscription checkout |
| Monitoring | CloudWatch or Datadog, plus paging alerts | |

### Phase 2: Growth

Upgrade each piece when it becomes the bottleneck, not on a schedule.

| Upgrade | Do it when |
|---|---|
| RDS → **Aurora PostgreSQL** (plus read replicas) | Database CPU or storage I/O stays high, or app reads slow down trade writes |
| Price history → **Timescale Cloud or ClickHouse** | Charts or strategy performance queries get slow on partitioned tables |
| Larger or clustered **ElastiCache** | Redis memory or connection limits are reached |
| **Autoscaling on SQS queue depth** | Trade queues back up during volatile markets |
| **Rule backtest workers** (ECS tasks started on demand) | Advanced mode launches |
| **Second chain** (for example Solana) | Users want tokens Base doesn't have |
| **Our own RPC node** | RPC rate limits or costs become a problem |

### Not on our roadmap

| Item | Why not |
|---|---|
| Holding customer funds in wallets we control | That's custody, and custody means licenses. Users own their wallets; our permission can only swap inside them |
| Our own key signing (KMS `secp256k1`, Nitro Enclaves, CloudHSM) | The wallet provider does signing in its secure enclaves |
| Kafka (MSK) | SQS is enough at our scale |
| DynamoDB for idempotency | The unique trade key in Postgres already prevents double trades |
| Customer-written code (Python strategies) | Running strangers' code on servers that can trade user funds is a security risk, needs an isolated container per strategy, and turns one engine per strategy into one per customer. Customers build rules from our building blocks instead |
| "Bring your own bot" developer API | Possible much later as a separate product, with its own security review |

### Environments

Separate AWS accounts and Privy apps for:
- **Dev:** Base Sepolia testnet, ramp sandboxes, fake data
- **Staging:** testnet, mirrors production, used for TestFlight / Play internal testing
- **Production:** Base mainnet, real money, locked down

### Infrastructure as code

Everything defined in Terraform or AWS CDK, so the agent team changes infrastructure through reviewed code, never by clicking in the console.

### Security baseline

- Encryption in transit and at rest
- Databases in private subnets, no public access
- Least-privilege IAM roles per service; only the trade router can use the authorization key
- MFA on every AWS, Privy, ramp and admin account
- Audit logging (CloudTrail) on; archives under S3 Object Lock
- Backups tested by actually restoring them
- Independent security review of the trade router and auto-trading permission before public launch
- Plan for a **SOC 2** audit as the business grows; partners and larger users will ask

### Rough cost

Phase 1: a few hundred dollars a month for AWS across staging and production, plus Privy's fees, gas sponsorship (a small amount per trade on Base) and the RPC provider. Ramp fees are paid by users at purchase and cash-out. *Estimate only; verify with each provider's pricing and the AWS pricing calculator.*

## Agent team rules

The system is built and maintained by an AI agent team. Money bugs are silent, so:

- A **different agent reviews** risk, trade router and permission code than the one that wrote it
- **Tests required on every money path:** duplicate signals, failed swaps, price moved, expired approvals, expired or revoked permissions, policy rejections, lost connections, queue redelivery
- **No agent changes risk limits, approved setting ranges, coin allowlists, wallet policies, the authorization key** or production infrastructure without owner approval
- **Weeks on Base Sepolia testnet**, then small amounts on mainnet, before real users
- **Owner personally reads** the risk engine, trade router and auto-trading permission code before launch

## Sources
- [NautilusTrader infrastructure crate (Redis/Postgres)](https://docs.rs/crate/nautilus-infrastructure/0.49.0)
- [NautilusTrader concepts overview](https://nautilustrader.io/docs/latest/concepts/overview/)
- [NautilusTrader home (latest v2 release, Python 3.13+)](https://nautilustrader.io/)
- [NautilusTrader 1.231.0 release notes (v2 transition notice)](https://newreleases.io/project/github/nautechsystems/nautilus_trader/release/v1.231.0)
- [NautilusTrader integrations](https://nautilustrader.io/docs/latest/integrations)
- [Privy: signers overview](https://docs.privy.io/wallets/using-wallets/signers/overview.md)
- [Privy: enabling offline actions (signers with policies)](https://docs.privy.io/controls/authorization-keys/owners/configuration/user/offline)
- [Privy: React Native quickstart](https://docs.privy.io/basics/react-native/quickstart.md)
- [Privy: smart wallets and gas sponsorship](https://docs.privy.io/wallets/using-wallets/evm-smart-wallets/overview.md)
- [Privy: native gas sponsorship](https://privy.io/blog/introducing-privy-native-gas-sponsorship)
- [What is Turnkey (non-custodial key infrastructure)](https://turnkey.com/what-is-turnkey)
- [Coinbase Developer Platform: Trade API (swaps on Base, powered by 0x)](https://docs.cdp.coinbase.com/swaps/welcome)
- [Base docs: integrate trading with the 0x Swap API](https://docs.base.org/build-on-base/integrate-defi/integrate-trading.md)
- [Coinbase Onramp and Offramp overview](https://docs.cdp.coinbase.com/onramp/docs/welcome/)
- [MoonPay off-ramp overview](https://dev.moonpay.com/docs/off-ramp-overview)
- [Amazon RDS for PostgreSQL: supported extensions](https://docs.aws.amazon.com/AmazonRDS/latest/PostgreSQLReleaseNotes/postgresql-extensions.html)
- [Timescale Cloud vs. Amazon RDS (no TimescaleDB on RDS)](https://timescale.com/go/amazon-rds-vs-timescale)
