# Product

[← Hub](README.md) · [Features](features.md) · [Technical](technical.md) · [Business](business.md)

## Concept

A crypto app for iPhone and Android where **users own their wallet and our strategies trade inside it**. Users add cash with Apple Pay, a debit card or a bank transfer, pick a risk level and strategies, and let them run automatically or approve each trade with one tap. They cash out to their bank whenever they want.

**We never hold customer money.** The wallet belongs to the user, licensed ramp partners handle dollars in and out, and trades execute on decentralized exchanges.

**Analogy:** the user's wallet is their own safe. We're the kitchen that cooks up the trades. With auto-trading on, the user hands us a key that opens one drawer only (swaps of allowed coins, within their limits) and never the front door (sending money out).

## Who holds what

| Piece | Who | What they do |
|---|---|---|
| Wallet and keys | **The user** | Owns the wallet, unlocks it with Face ID, and is the only one who can send money out |
| Key security | Wallet provider (Privy) | Keeps keys in secure hardware and enforces the limits of each auto-trading permission |
| Dollars in and out | Ramp partners (Coinbase, MoonPay) | Card and bank purchases, cash-outs to bank, and the ID checks those require |
| Trade execution | Decentralized exchanges on Base, through the 0x aggregator | Swaps one token for another at the best available route |
| Strategies, signals, trade building, auto-trading | **Us** | Decide trades, size them for each user, and execute them inside the user's permission or send them for approval |

**Later track:** a brokerage version through a licensed CaaS partner (Alpaca first) for users who want a broker holding their money, plus stocks. See [Business: Later brokerage track](business.md#later-brokerage-track).

## How a trade flows

1. User signs up with email or Apple; the app creates their wallet (Face ID passkey, no seed phrase)
2. User adds cash: buys USDC with Apple Pay, a debit card or a bank transfer through a ramp partner; it lands in their wallet as their cash balance
3. User picks a risk level and strategies, or builds a rule, sets their limits, and chooses **Auto-trade** or **Approve each trade**
4. For Auto-trade, the user grants a scoped trading permission with Face ID
5. Nautilus watches prices and fires a signal
6. The trade router checks each subscribed user's mode, limits and balance, and builds their swap with price protection
7. **Auto-trade:** the router executes it inside the user's permission. **Approve:** push notification, the user confirms with Face ID, and their wallet signs
8. The swap settles on Base; the app updates balances, sends a notification and logs the trade for taxes
9. Cash out anytime: sell to cash (USDC), then a ramp partner deposits dollars to their bank

Technical detail: [Technical: Architecture](technical.md#architecture).

## Trading modes

Every strategy subscription and every customer rule runs in one of two modes, and so does "hold this mix" (owner, 2026-11-20). The user chooses, and can switch anytime.

| | Auto-trade | Approve each trade |
|---|---|---|
| How it works | Trades execute automatically inside the user's trading permission | Push notification; the user taps approve and confirms with Face ID |
| Works for | Our strategies, customer rules and "hold this mix" | Our strategies, customer rules and "hold this mix" |
| Best for | Hands-off users; strategies where timing matters | Users who want a say on every trade |
| Downside | The user isn't in the loop on each trade | Missed trades, notification fatigue |

Auto-trade is **opt-in per strategy, rule or held mix**: turning it on shows the permission screen. Both modes are available at launch for our strategies and for customer rules, by owner decision (2026-11-19). "Hold this mix" runs in either mode too (owner, 2026-11-20); its phase is still proposed. The risks are recorded in [Business: Accepted risks](business.md#accepted-risks).

### The auto-trading permission

What the user sees before granting it:

> **Let [App] trade for you**
> ✓ Swap between your cash (USDC) and the coins allowed for your risk level
> ✓ Up to $X per trade and $Y per day
> ✓ Only through approved exchanges, with price protection on every trade
> ✗ Can never send money out of your wallet
> ✗ Can never change your limits or this permission
> Expires in 90 days · Turn off anytime in Account → Auto-trading

- Granted with Face ID; the user stays the owner of their wallet
- The limits are enforced by the wallet provider, not only by our code
- **Pause everything** and turning off Auto-trade revoke the permission immediately

Technical detail: [Technical: Auto-trading permission](technical.md#auto-trading-permission).

## Strategies by risk level

Customers choose how much risk they want, and each risk level has its own strategies. Every strategy runs in NautilusTrader. Coins are limited to tokens with deep trading on Base.

| Risk level | For someone who… | Launch strategy | Add later | Guardrails |
|---|---|---|---|---|
| **Steady** | Wants smaller swings | **Rebalancing:** holds BTC, ETH and a slice of cash (USDC); trades only when the mix drifts | Trend following that moves to cash in downtrends | BTC and ETH only; always part cash; a few trades a month |
| **Balanced** | Is OK with normal crypto swings | **Dip buying:** buys BTC or ETH after a set drop, with a cap on how much | A second dip strategy with different timing | BTC, ETH and a few vetted large tokens; stop-loss required |
| **Bold** | Accepts big drops for bigger upside | **Momentum:** holds the strongest few from a vetted list of the most liquid tokens on Base; rotates weekly | Mean reversion, grid trading | Wider token list, more trades, biggest possible drops |

**Steady, for now.** The lab's first rebalancing study found no edge (NO EDGE; SCOUTING, from the lab's simple in-house simulator, not NautilusTrader; see [Features: What the first Steady study taught](features.md#what-the-first-steady-study-taught)). So Steady's own tested strategy is still to be found; the plan above stands until the owner changes it. Meanwhile, Steady customers can use **"hold this mix"**, a self-directed tool like recurring buys, not one of our strategies (owner, 2026-11-20). The customer picks the crypto share, the BTC/ETH split and a drift band, and the app keeps the mix within the band (owner, 2026-11-20). The app makes no claim it beats anything and shows the mix's backtested worst fall, labeled hypothetical. The owner decided three more points on 2026-11-22 ([record](../../reports/director/2026-11-22-owner-answers-hold-mix.md)):
- **A default that depends on wallet size:** wallets up to 5,000 USD default to a 30% drift band with at most 2 rebalances in any 30 days, larger wallets to 50% with at most 1. Customers can still pick either band and any cap up to 2. The owner was asked this twice; the second answer, "Tighter for small wallets", supersedes the first, "Same for everyone", whose question had the study's finding backwards. The study simulated 500, 5,000 and 50,000 USD wallets only, so the 5,000 USD line is the owner's choice.
- **A hard Steady limit of at most 2 rebalances in any 30 days,** for this tool only, not our Steady strategies. It never holds back a trade that fixes a Steady limit (a pause still does).
- **A mix that fell more than 35% in the past** (Steady's drawdown budget) is shown as Balanced or Bold, not Steady.

The numbers behind them are SCOUTING and are rechecked with measured Base costs before customers see them. See [Features: Hold this mix](features.md#hold-this-mix).

### How the levels work

- **Customers choose, we label.** Each customer picks their own level; strategies are grouped and labeled by level. The app doesn't recommend a level or a strategy for a specific person.
- **Going above your level:** subscribing to a strategy above the customer's chosen level shows a clear warning and needs a confirm.
- **Levels are measured, not marketed.** Each level has a range for its worst expected drop, set from backtests and live results. A strategy whose live results move outside its level's range is halted automatically and reviewed.
- **Guardrails are enforced twice:** by the trade router, and by the auto-trading permission's token allowlist inside the wallet provider.
- **Bitcoin is held as cbBTC**, a token on Base backed 1:1 by bitcoin held by Coinbase. The app says this plainly.
- **Built once, tuned by settings.** Each strategy is one Nautilus strategy plus a settings file (coins, sizes, stops), so new variants are mostly new settings, not new code. Customers can adjust a strategy's settings within the approved range (tested by the lab, approved by the owner); see [Features: Adjustable strategy settings](features.md#adjustable-strategy-settings).
- **All costs included.** Backtests include swap fees, price slippage and gas. This matters most for Bold, which trades the most.
- **Never at any level:** leverage, short selling, market making or arbitrage.

### How the launch strategies behave

| Strategy | Level | Wins when | Loses when |
|---|---|---|---|
| Rebalancing (with cash) | Steady | Most conditions, modestly; cash cushions crashes | Rarely big, rarely exciting; lags in strong rallies |
| Dip buying | Balanced | Long-term uptrend | Long crash (keeps buying down; the cap limits how much) |
| Momentum rotation | Bold | Strong runs in a few tokens | Choppy markets and sudden reversals |

These three behave differently, so they shouldn't all lose at the same time.

## Features

Full catalog by area, tab and phase: [Features](features.md).

### Recommended features (ranked)

**Build first:** auto-trading with a clear, limited permission, demo mode, honest strategy cards, and "why did this trade happen" explanations. Together they make this "the crypto app I actually trust."

**Must-haves**
1. **Simple onboarding:** sign-up and a wallet in under a minute (Face ID, no seed phrase); ID checks only happen at the ramp partner when buying or cashing out
2. **Clear portfolio screen:** what I own, my cash, what I've made or lost, every trade
3. **Add cash and cash out:** Apple Pay, debit card or bank in; cash out to bank
4. **Recurring buys:** "Buy $25 of BTC every Friday"
5. **Personal limits and Pause everything:** max per trade and per day, a loss limit, one tap to stop everything and revoke auto-trading
6. **Security:** Face ID for sends and permission changes, address book and warnings for new addresses, wallet recovery
7. **Tax export:** no broker sends users tax forms, so one-button export with cost basis matters from day one

**Standout features** (what makes it more than a wallet)

8. **Auto-trading with a clear, limited permission:** plain-English limits, enforced by the wallet provider, revocable anytime
9. **Demo mode:** try any strategy with fake money first; best sales tool
10. **Honest strategy cards:** risk level, worst losing streak and biggest drop, not just gains
11. **"Why did this trade happen?":** a one-line plain-English reason on every trade
12. **One-tap signal approval:** for users who want to approve each trade
13. **AI rule builder (Phase 2):** plain English → a rule the customer reviews and confirms

**Nice-to-haves (later)**

14. **Weekly recap:** trades made, how they did, and why
15. **Strategy leaderboard:** live results only, never backtests
16. **Copy trading**

### Features by phase

**Phase 1 — Lean launch (self-custody)**

*Account and wallet*
- Sign-up with email or Apple (Privy); wallet created automatically
- Face ID passkey, no seed phrase; wallet recovery
- Gas sponsored: users never need ETH to pay network fees

*Money in and out*
- Add cash: Apple Pay, debit card or bank through a ramp partner (Coinbase Onramp or MoonPay); arrives as USDC
- Cash out to bank through a ramp partner
- Cash shown as a dollar balance (USDC)
- Receive and send crypto: Face ID, address book, warning on new addresses

*Portfolio*
- Balances, cash, profit/loss, trade history (with a link to each trade on the blockchain)

*Trading*
- Manual buy/sell (swaps) and recurring buys
- "Hold this mix" (proposed for Phase 1): the customer picks a crypto and cash mix and a drift band (no tighter than 30%, owner; 30% or 50%, the lab's reading; by default 30% with at most 2 rebalances in any 30 days for wallets up to 5,000 USD, and 50% with at most 1 above (owner, 2026-11-22); and at most 2 in any 30 days for every wallet), and the app keeps the mix within the band, on Auto-trade or Approve; labeled as their own choice, with the backtested worst fall shown and labeled hypothetical; a mix that fell more than 35% in the past is shown as Balanced or Bold, not Steady (owner, 2026-11-22). See [Features: Hold this mix](features.md#hold-this-mix)

*Strategies*
- Risk levels: customer picks Steady, Balanced or Bold; strategies grouped and labeled by level; warning and confirm to go above it
- Strategy library: one starter strategy per risk level (rebalancing, dip buying, momentum)
- Strategy cards: plain-English description, risk level, worst historical drop, backtest and live results shown **separately and clearly labeled**
- Strategy settings, as ranges are approved: adjust within the approved range (tested by the lab, approved by the owner), with the backtested worst fall for the chosen settings shown and labeled hypothetical
- Rule builder, simple mode: templates like "buy $X when BTC drops Y%," with stop-loss required
- Trading mode per strategy and rule: Auto-trade or Approve each trade
- Auto-trading permission screen; manage and revoke permissions in Account

*Customer risk controls*
- Max amount per trade and per day (also enforced inside the auto-trading permission)
- Daily/weekly loss limit that auto-pauses the customer's strategies, their own rules and "hold this mix"; a pause stops trading and doesn't sell
- One big **Pause everything** button that also revokes auto-trading

*Demo mode*
- Paper trading with fake money so new users can try strategies risk-free

*Notifications*
- Trade executed, signal waiting for approval, limit hit, strategy paused, cash in/out status, permission expiring

*Tax*
- Downloadable trade history with cost basis, built from on-chain records

**Phase 2 — Growth**
- **AI copilot:** explains market moves, explains why a signal fired, turns plain-English requests into rules the customer reviews and confirms
- **Advanced rule builder (paid tier):** more building blocks (moving averages, RSI, price change, AND/OR conditions, several coins, take-profit), plus a Backtest button with all costs included and results labeled hypothetical. See [Technical: Customer rules](technical.md#customer-rules-and-advanced-mode)
- More strategies at each risk level (see [Strategies by risk level](#strategies-by-risk-level))
- Connect an existing wallet (MetaMask, Coinbase Wallet and others)
- More chains (for example Solana) for a wider token list
- Strategy performance leaderboard (live results only)
- Education hub: short lessons tied to each strategy
- Referral program
- Home-screen widgets and Apple Watch / Wear OS glanceable balances
- Richer tax reports / integrations with tax software

**Phase 3 — Later tracks**
- **Brokerage version** through a CaaS partner for users who want bank deposits held by a broker, plus stocks
- Performance fees
- Social / copy trading

**Not planned:** customer-written code (security risk, and it breaks one engine per strategy). A developer API for customers' own bots is possible much later as a separate product.

## Mobile app

### Framework

**Recommendation: React Native with Expo** — one TypeScript codebase that ships to both the App Store and Google Play. Privy's Expo SDK provides login, wallets and passkeys.

| Option | Pros | Cons |
|---|---|---|
| **React Native + Expo** ✅ | One codebase; TypeScript shared with backend tooling; large ecosystem (biometrics, charts, push, Privy's Expo SDK); over-the-air updates for non-native fixes; agent teams write TypeScript well | Some native modules needed for deep platform features |
| Flutter | One codebase; smooth UI | Dart is a separate language from the rest of the stack; smaller crypto SDK ecosystem |
| Native (Swift + Kotlin) | Best performance and platform feel | Two codebases, roughly double the work and bugs |

Charts are the most performance-sensitive piece; use a native-backed charting library rather than web-view charts.

### App structure (main tabs)

1. **Home:** total balance (coins and cash), today's change, active strategies with their mode (Auto or Approve), anything waiting for approval
2. **Strategies:** strategies grouped by risk level, honest strategy cards, subscribe with Auto-trade or Approve, rule builder (simple and advanced mode)
3. **Trade:** buy/sell, recurring buys, hold this mix (proposed), Add cash, Cash out
4. **Activity:** every trade with its "why did this happen" reason and blockchain link, cash in and out
5. **Account:** wallet (address, receive, send, recovery), auto-trading permissions, limits, Pause everything, risk level, security, tax export, demo mode toggle

### Auto-trade flow

1. Strategy fires → the trade router builds the user's swap with price protection
2. The router executes it inside the user's permission; the wallet provider checks every limit before signing
3. Push notification after the fact: "Bought $100 of BTC — BTC dropped 6% today"
4. The trade appears in Activity with its reason

### Signal approval flow (Approve mode)

1. Strategy fires → backend sends a high-priority push notification
2. Notification shows the trade in plain English ("Buy $100 of BTC — dropped 6% today")
3. Tap → app opens straight to the approval screen (deep link)
4. Face ID → the user's own wallet signs the swap
5. Signals expire after a set time; expired signals are never executed late

Push delivery isn't guaranteed (phone off, notifications disabled), so the Home tab always shows pending approvals too.

### Mobile security

- Face ID passkey unlocks the wallet; Face ID confirms sends, approvals and permission changes
- Private keys never live in the app or on our servers; they stay in the wallet provider's secure hardware
- No API keys or secrets inside the app binary; the app only talks to our backend and the wallet provider
- TLS everywhere with certificate pinning for our API
- Jailbreak/root detection with reduced functionality on compromised devices
- Screenshot/app-switcher blurring on balance and account screens
- Remote session revoke from the Account tab and admin dashboard

### Release process

- Expo EAS for builds and store submissions; over-the-air updates only for JavaScript fixes, never to change trading or permission logic without a review
- Three app variants: dev (Base Sepolia testnet), staging (testnet, TestFlight / Play internal testing), production (Base mainnet)
- Closed beta through TestFlight and Play internal testing before public launch
- Crash and error reporting from day one

**App store approval is the biggest launch risk.** Apple's crypto rules and subscription fees are in [Business: App store rules](business.md#app-store-rules).
