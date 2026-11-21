# Self-Custody Algo Trading App

*Living docs. Started 2026-11-18. Direction changed 2026-11-19 to a lean self-custody launch; the brokerage (CaaS partner) version moved to a later track.*

An **iOS and Android** crypto app where users own their wallet and our strategies trade inside it. Each user gets a wallet in the app that only they control (Face ID, no seed phrase). They add cash with Apple Pay, a debit card or a bank transfer, our strategies trade in their wallet automatically or with one-tap approval, and they cash out to their bank anytime. **We never hold customer money.**

## Docs

| Doc | What's in it |
|---|---|
| [Features](features.md) | What the app does and offers, full feature catalog by area, tab and phase, key flows, what it doesn't do |
| [Product](product.md) | Concept, who holds what, how a trade flows, trading modes, the auto-trading permission, strategies by risk level, ranked features, features by phase, mobile app |
| [Technical](technical.md) | Architecture, trade router, auto-trading permission, launch chain, wallets, rule engine, Nautilus engine, database, phased AWS hosting, agent team rules |
| [Business](business.md) | Partners and call questions, revenue, app store rules, regulation, accepted risks, compliance checklist, later brokerage track |
| [Strategy Lab](../../AGENTS.md) | Guide for the coding agents (repo root): NautilusTrader setup, data, mass simulation, validation gates, prediction models ([research methods](../../research-methods.md)) |

## Decisions

| Topic | Decision | See |
|---|---|---|
| Direction | **Lean self-custody launch:** users own their wallets; we provide strategies and auto-trading. Brokerage version through a CaaS partner moved to a later track | [Product](product.md#concept) |
| Platforms | Native mobile apps for **iOS and Android** | [Product](product.md#mobile-app) |
| Mobile framework | React Native + Expo (one codebase, both stores) | [Product](product.md#framework) |
| Wallets and login | **Privy**: user-owned embedded wallets, Face ID passkey, no seed phrase; also handles login (replaces Cognito). Turnkey as the alternative | [Technical](technical.md#wallets-and-login) |
| Launch chain | **Base**: USDC as the cash balance, cbBTC for bitcoin, low fees, network fees sponsored; swaps through the 0x aggregator | [Technical](technical.md#launch-chain-and-trading) |
| Money in and out | Licensed ramp partners: Coinbase Onramp/Offramp and MoonPay | [Business](business.md#ramp-partners) |
| Trading modes | Every strategy, rule and "hold this mix" runs on **Auto-trade** or **Approve each trade**, chosen by the user. Auto-trade is available at launch for our strategies and customer rules; "hold this mix" runs in either mode too (owner, 2026-11-20) | [Product](product.md#trading-modes) |
| Auto-trading permission | User-granted, revocable signer on the user's wallet, enforced by the wallet provider: swaps only, allowed coins only, amount caps, money can never leave the wallet, 90-day expiry | [Technical](technical.md#auto-trading-permission) |
| Trading engine | **NautilusTrader only** (v2, pinned): backtest, paper and live with the same strategy code; one instance per strategy | [Technical](technical.md#engine) |
| Strategy research | Strategy Lab (repo root): Optuna search, walk-forward and purged cross-validation, Deflated Sharpe and overfitting checks, MLflow tracking; prediction models for volatility, regime and ranking | [Strategy Lab](../../AGENTS.md) |
| Engine vs. user trades | Nautilus decides *what* to trade on its own paper model account and sends a signal; our trade router sizes and executes each user's swap. Nautilus never touches user wallets. For customers off a strategy's default settings, see [Strategy settings](technical.md#strategy-settings) (proposed; needs an owner decision) | [Technical](technical.md#who-does-what-nautilus-vs-the-trade-router) |
| Customer-built strategies | Rules stored as small versioned records (data, not code), run by one shared rule engine. Simple mode at launch; advanced mode with backtests in Phase 2 (paid tier). No customer-written code | [Technical](technical.md#customer-rules-and-advanced-mode) |
| Strategy settings | Customers can adjust a strategy's settings (for Steady: crypto share, BTC/ETH split, drift band, check frequency, loss limit). Each has a default and an approved range (tested by the lab, approved by the owner; in AGENTS.md since 2026-11-20, owner: "yes to 1"); the risk level's limits cap it; past the range it becomes the customer's own rule (proposed; director report decision 6, open) | [Features](features.md#adjustable-strategy-settings) |
| Strategy lineup | Three risk levels customers choose themselves: Steady (rebalancing), Balanced (dip buying), Bold (momentum). Coins limited to tokens with deep trading on Base. No leverage or shorting at any level | [Product](product.md#strategies-by-risk-level) |
| "Hold this mix" (Steady) | A **self-directed tool** like recurring buys, not one of our strategies (owner, 2026-11-20). The customer picks the crypto share, BTC/ETH split and a drift band (capped by Steady's "a few trades a month"; the customer sets the number and the app recommends one); the app trades back to the mix when BTC or ETH leaves the band or a Steady limit is hit, and optionally on a long reset schedule. It runs on Auto-trade or Approve, the customer's choice, and their loss limit pauses it (owner, 2026-11-20). No claim it beats anything; the backtested worst fall for the mix is shown, labeled hypothetical. Steady's own tested strategy is still to be found: the first rebalancing study found no edge (SCOUTING) | [Features](features.md#hold-this-mix) |
| Backend language | Python (FastAPI), matching NautilusTrader | [Technical](technical.md#architecture) |
| Database | Shared PostgreSQL with per-user Row-Level Security, append-only ledger mirroring the chain, Redis; price history in date-partitioned Postgres tables | [Technical](technical.md#database) |
| Hosting | AWS, phased: lean launch on ECS Fargate, RDS Multi-AZ, SQS, KMS; upgrades only when load calls for it; infrastructure as code | [Technical](technical.md#hosting) |
| Legal review | Skipped before launch by owner decision; risks and mitigations recorded | [Business](business.md#accepted-risks) |
| Later track | Brokerage version through a CaaS partner (Alpaca first) for bank-deposit users and stocks | [Business](business.md#later-brokerage-track) |
| Build team | AI agent team builds and maintains; owner personally reviews risk, trade router and permission code | [Technical](technical.md#agent-team-rules) |

## Roadmap

| Step | What | See |
|---|---|---|
| 1 | Strategy Lab: NautilusTrader set up, historical data in the catalog, the three launch strategies built, mass simulation and validation | [Strategy Lab](../../AGENTS.md) |
| 2 | Approved strategies run on paper model accounts; optionally small amounts of own money | [Product](product.md#strategies-by-risk-level) |
| 3 | Privy set up: login, embedded and smart wallets, gas sponsorship, signers and policies, on Base Sepolia testnet | [Technical](technical.md#wallets-and-login) |
| 4 | Backend foundations (Phase 1 hosting): AWS accounts, RDS Postgres, Redis, SQS, KMS, S3 Object Lock, infrastructure as code | [Technical](technical.md#phase-1-launch) |
| 5 | Trade router, 0x swap builder, risk engine, auto-trading permission, chain watcher; testnet first | [Technical](technical.md#architecture) |
| 6 | Ramp integrations in sandbox: Coinbase Onramp/Offramp and MoonPay | [Business](business.md#ramp-partners) |
| 7 | Mobile app MVP (React Native + Expo) against testnet | [Product](product.md#mobile-app) |
| 8 | Disclosures, terms, permission screen wording, app store review package | [Business](business.md#compliance-checklist) |
| 9 | Closed beta via TestFlight / Play internal testing on Base mainnet, small limits | [Product](product.md#release-process) |
| 10 | App Store and Google Play submission, public launch | [Business](business.md#app-store-rules) |

## Open questions

- [ ] Apple review: will in-app swaps be treated as exchange features under Guideline 3.1.5? How do comparable self-custody wallets get approved?
- [ ] Ramp partners: fees, state coverage, and which to use for buying vs. cashing out (Coinbase Offramp needs a Coinbase account; MoonPay selling isn't available in Louisiana, Texas or New York)
- [ ] Which auto-trading policy conditions Privy enforces natively (contract, calldata, token, amount, expiry)
- [ ] Final coin list per risk level on Base
- [ ] Steady limits and drawdown budget: together they set how much crypto a Steady customer can pick (see [Features: Adjustable strategy settings](features.md#adjustable-strategy-settings))
- [ ] "Hold this mix": if no Steady strategy of ours passes by launch, does Steady launch with the tool only? See [Features: open questions](features.md#open-questions-that-change-the-feature-set)
- [ ] "Hold this mix": Steady's "a few trades a month" caps the drift band the customer picks (owner, 2026-11-20). The customer sets the cap's number and the app recommends one based on the lab's data and simulations (owner, 2026-11-20; the lab's simulation is in progress, on 2017-2022 data only). It counts rebalances and is enforced as a minimum wait between them (decided by the lab; owner, 2026-11-21: "you decide"). What number to recommend, and does Steady keep an upper limit above the customer's number? See [Features: open questions](features.md#open-questions-that-change-the-feature-set)
- [ ] Strategy settings: accept a per-customer decision check outside Nautilus, or keep Nautilus as the only decision-maker (fixed settings at launch, or one Nautilus node per approved combination)? See [Technical: Strategy settings](technical.md#strategy-settings)
- [ ] Subscription price, given gas sponsorship, Privy and RPC costs
- [ ] Subscriptions: in-app purchase only, or also US web checkout?
- [ ] Fee model: subscription only, or also a small swap fee later
- [ ] App name and brand
- [ ] Parked legal questions (not blocking): see [Business: Open legal questions](business.md#open-legal-questions-not-blocking)
