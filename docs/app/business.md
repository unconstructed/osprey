# Business

[← Hub](README.md) · [Features](features.md) · [Product](product.md) · [Technical](technical.md)

*Not legal advice. By owner decision, the app launches without a legal review; the risks of that choice are recorded in [Accepted risks](#accepted-risks).*

## Partners

The lean launch doesn't need a licensed partner to hold customer money, because users hold their own. It needs four kinds of partners instead.

### Wallet provider

| Partner | Fit | Notes |
|---|---|---|
| **Privy** | ⭐ First pick | Expo / React Native SDK; embedded wallets with passkeys and no seed phrase; **signers with policies** for trades while the user is offline (Privy's own docs list limit orders, agentic trading and portfolio rebalancing); smart wallets; native gas sponsorship |
| **Turnkey** | Alternative | Non-custodial key infrastructure in secure enclaves; programmable policy engine |

### Ramp partners

Dollars in and out. They carry the licenses and run the ID checks for buying and cashing out.

| Partner | Fit | Notes |
|---|---|---|
| **Coinbase Onramp / Offramp** | ⭐ First pick for buying | Native to Base and USDC. Guest checkout lets US users without a Coinbase account deposit up to $500 a week with Apple Pay and debit cards. Offramp deposits to a bank (ACH) or Coinbase account, but **requires a Coinbase account with a linked bank**. Access is by application |
| **MoonPay** | ⭐ First pick for cashing out | In-app buy and sell widget; no Coinbase account needed; deposits to US bank accounts by ACH. **Selling isn't available in Louisiana, Texas or New York.** One industry estimate puts fees around 1% for bank transfers and up to about 4.5% for cards, plus a price spread; revenue share is negotiated for high-volume partners |

### Trading and blockchain access

| Partner | Role |
|---|---|
| **0x Swap API** | Routes swaps across decentralized exchanges on Base for the best price; also powers Coinbase's developer Trade API |
| **Managed RPC provider** (for example Alchemy) | Reads balances and submits transactions on Base |

### Partner call questions

**Privy**
1. Which policy conditions are supported natively (contract address, calldata, token, amount per transaction, amount per day, expiry)?
2. Pricing per user, per signature and for gas sponsorship
3. Uptime commitments, and what happens to signers during an outage
4. Wallet export and recovery options for users
5. Examples of approved App Store and Google Play apps using signers for automated trading

**Ramp partners (Coinbase, MoonPay)**
1. Fees, spreads and revenue share for our volume
2. US state coverage for buying and for selling
3. In-app experience: embedded flow or hosted page; how the ID check works on mobile
4. USDC on Base supported for both buying and cashing out?
5. Can they provide licensing evidence for Apple review of our buy and sell features?

**0x**
1. Fees, integrator fee options and rate limits on Base

## Revenue

| Phase | Revenue |
|---|---|
| 1 | **Subscription** for premium strategies and auto-trading. A small per-swap fee is possible later; see [Accepted risks](#accepted-risks) |
| 2 | Higher tiers (AI copilot, advanced rule builder with backtests, more strategies); ramp revenue share at volume |
| Later | Brokerage track: trading fees through the CaaS partner; performance fees |

**Costs the subscription must cover:** Privy, gas sponsorship, RPC, swap aggregator fees (if any) and AWS. Ramp fees are paid by users when they buy or cash out.

App store fees affect subscription pricing; see [App store rules](#app-store-rules).

## App store rules

Still the biggest launch risk.

### Apple (App Store Review Guideline 3.1.5)
- **Wallets:** apps may facilitate virtual currency storage if they're offered by developers enrolled as an organization.
- **Exchanges:** apps may facilitate crypto transactions on an approved exchange only in regions where the app has the licensing and permissions to provide a crypto exchange.
- Apple has rejected apps that facilitate the transmission of crypto without being submitted by an exchange or recognized financial institution.

### Google Play
- Google's licensing policy covers custodial exchanges and wallets. Google states that **non-custodial wallets are out of scope** of its Cryptocurrency Exchanges and Software Wallets policy.
- Declare the app's features accurately in the Play Console.

### Our path
- Publish under our own registered company (organization developer accounts on both stores)
- Buying and cashing out happen inside licensed ramp partners' flows; ask them for licensing evidence for Apple review ([partner questions](#partner-call-questions))
- Swaps execute from the user's own wallet on decentralized exchanges; review notes explain the non-custodial design and the auto-trading permission
- Study how comparable self-custody wallets with built-in swaps get approved, and match their approach
- **Fallback if Apple objects to in-app swaps:** ship iOS with a reduced feature set while appealing, or bring the [brokerage track](#later-brokerage-track) forward for iOS

### Paying for subscriptions in the app
- Selling premium strategies or auto-trading inside the app is a digital subscription, which normally goes through Apple/Google in-app purchase (15–30% fee).
- **US Apple:** apps can link out to web checkout and currently pay Apple no commission on those sales, but must still offer in-app purchase alongside. A final court decision on what Apple may charge is expected in 2027.
- **US Google:** since October 1, 2026, US developers using alternative billing must report transactions and pay Google's service fees.
- Swaps and ramp purchases are financial transactions, not digital goods, and don't go through app store billing.

Plan pricing assuming in-app purchase fees; treat web checkout savings as upside.

## Regulation

*As of November 2026.*

- **Non-custodial software:** FinCEN's 2019 guidance says software wallet providers and decentralized exchanges are not money transmitters. The test is control: a wallet the provider can spend from is custodial; one only the user can spend from generally isn't.
- **Enforcement risk anyway:** in the Samourai Wallet case, FinCEN told prosecutors the non-custodial wallet wasn't a money services business, and its founders were charged regardless. DOJ guidance issued since then bars prosecutors from charging non-custodial software tools with unlicensed money transmission.
- **No US crypto market structure law yet.** The Senate rejected cloture on the CLARITY Act 49–50 on September 15, 2026, effectively ending it for this Congress. Agencies (SEC, CFTC) are moving ahead with their own rules, which future leadership can change.
- **Stablecoins** are governed by the GENIUS Act (law since 2025); relevant because USDC is the app's cash balance.
- **Automated trading on users' behalf:** Coinbase registered as an SEC Registered Investment Adviser and a CFTC/NFA Commodity Trading Advisor before offering AI-driven trading. That's the closest precedent for auto-trading our strategies.
- **Pattern Day Trader rule eliminated** for stocks (effective June 4, 2026); relevant to the brokerage track if stocks are added.

### Risk levels: customers choose, we label
- Customers pick their own risk level (Steady, Balanced, Bold); we label strategies by level. See [Product: Strategies by risk level](product.md#strategies-by-risk-level).
- The app doesn't recommend a level or a strategy for a specific person.
- Risk labels are backed by measured results (worst expected drop per level), with backtests labeled hypothetical, so the labels themselves aren't misleading marketing.

## Accepted risks

**Owner decision (2026-11-19):** launch with auto-trading for both our strategies and customer rules, without a legal review.

**Owner decision (2026-11-20):** "hold this mix" (a self-directed tool; see [Features: Hold this mix](features.md#hold-this-mix)) also runs on Auto-trade or Approve, the customer's choice. So the acceptance above covers it too.

| Risk | What could happen | How we reduce it |
|---|---|---|
| **Auto-trading our strategies looks like managing money** | Regulators could treat it as acting as an investment adviser or commodity trading advisor; Coinbase registered as both before offering AI-driven trading | Opt-in per strategy; the user picks the strategy and risk level; plain-English permission; the user's own limits; revocable anytime; no performance fees; honest strategy cards with backtests labeled hypothetical |
| **Our signer looks like "control" of funds** | Custody turns on control; a server that can trade in user wallets could be argued to have partial control | Swaps only, allowed tokens only, money can never leave the wallet, amount caps, 90-day expiry, enforced inside the wallet provider; the user stays the owner and can revoke |
| **A per-swap fee looks like brokering** | Taking a cut of each trade can raise broker questions | Launch subscription-only; add a swap fee later as a deliberate decision |
| **App store rejection** | Apple treats in-app swaps as exchange features | Organization accounts, ramp partners' licenses, non-custodial review notes, comparable approved apps, iOS fallback plan |
| **Enforcement despite guidance** | Non-custodial developers have been charged even when FinCEN said no license was needed | Stay strictly non-custodial; no mixing or privacy features; sanctions screening |
| **Wrapped bitcoin** | cbBTC depends on Coinbase holding the real bitcoin | Disclose it plainly in the app |
| **Smart contract or exchange exploits** | A bug in a decentralized exchange or wallet contract loses user funds | Only major contracts through 0x; token allowlist; amount caps |

### Open legal questions (not blocking)
Parked for whenever a review makes sense:
- Does auto-trading our strategies inside user wallets require adviser or trading-advisor registration?
- Does a scoped, revocable trading permission count as control or custody?
- Does a per-swap fee make the app a broker?
- Do self-selected risk levels with labeled strategies count as personalized advice?

## Compliance checklist

**Before beta**
- [ ] Terms of service, privacy policy, risk disclosures (auto-trading, what each risk level means, cbBTC, network and ramp fees)
- [ ] Auto-trading permission screen wording, reviewed against what the policy actually enforces
- [ ] Performance claims: backtests (ours, customers' own rule backtests and the worst fall shown for "hold this mix") labeled as hypothetical, live results shown separately; "hold this mix" labeled as the customer's own choice, with no claim it beats anything
- [ ] Company registered; Apple and Google developer accounts under the company name
- [ ] Sanctions screening of wallet addresses, and geoblocking of sanctioned countries
- [ ] Privy, ramp partner and 0x terms accepted; ramp partners' licensing evidence collected for app review

**Before public launch**
- [ ] Complaint handling process
- [ ] Record retention policy (ledger and audit log)
- [ ] Incident response plan (hack, bad trade, provider outage, signing key compromise)
- [ ] Independent security review of the trade router and auto-trading permission
- [ ] SOC 2 readiness as the business grows

**Before the brokerage track**
- [ ] CaaS partner onboarding and compliance review
- [ ] Adviser registration decision

## Later: brokerage track

A second version for mainstream users who want a broker holding their money and bank deposits instead of a wallet, plus stocks later. The trade router stays the same; only the piece that executes trades changes, from swaps on Base to orders through a CaaS partner.

| Partner | Fit | Notes |
|---|---|---|
| **Alpaca Broker API** | ⭐ First call | Free self-serve sandbox; crypto supplied by Kraken across 49 US states; orders per customer account; stocks, options and bonds too |
| **Zero Hash** | Strong alternative | Broadest US licensing (50+ state money transmitter licenses); clients include Interactive Brokers, Public and MoneyLion; sales-led |
| **BitGo** | Alternative | Publicly traded custody company with a crypto-as-a-service product for fintechs |
| **Kraken Embed** | Direct option | Same liquidity as Alpaca without the middleman; negotiated pricing; aimed at banks and established fintechs |
| Coinbase CaaS, Paxos, Bakkt | Not a fit yet | Built for large banks and brokers, or mid-pivot |

## Sources

**Wallets and ramps**
- [Privy: signers overview](https://docs.privy.io/wallets/using-wallets/signers/overview.md)
- [Privy: enabling offline actions](https://docs.privy.io/controls/authorization-keys/owners/configuration/user/offline)
- [Privy: smart wallets and gas sponsorship](https://docs.privy.io/wallets/using-wallets/evm-smart-wallets/overview.md)
- [What is Turnkey](https://turnkey.com/what-is-turnkey)
- [Coinbase Onramp and Offramp overview](https://docs.cdp.coinbase.com/onramp/docs/welcome/)
- [Coinbase Offramp overview](https://docs.cdp.coinbase.com/onramp-&-offramp/offramp-apis/offramp-overview)
- [Coinbase Onramp and Offramp docs (guest checkout limit)](https://docs.cdp.coinbase.com/onramp/docs)
- [Coinbase onramp demo app (Offramp needs a Coinbase account)](https://awesome.ecosyste.ms/projects/github.com%2Fcoinbase%2Fonramp-demo-application)
- [MoonPay FAQ (states where selling is unavailable)](https://dev.moonpay.com/v1.0/docs/faqs)
- [MoonPay overview and fee estimates (RailsMap)](https://railsmap.vercel.app/project/moonpay)
- [Coinbase Developer Platform: Trade API powered by 0x](https://docs.cdp.coinbase.com/swaps/welcome)

**App stores**
- [Apple 3.1.5 wallet and exchange rules (FX News Group)](https://fxnewsgroup.com/forex-news/cryptocurrency/apple-revises-app-store-rules-for-crypto-apps-nft-payments/)
- [Apple Developer Forums: rejection for transmitting crypto without an exchange](https://origin-devforums.apple.com/forums/profile/wuyanqu)
- [Apple Developer Forums: Guideline 3.1.5 rejections](https://developer.apple.com/forums/thread/810590)
- [Decrypt: Google confirms non-custodial wallets are exempt](https://decrypt.co/335134/google-non-custodial-wallets-exempt-new-crypto-app-rules-play-store)
- [Google Play Help: Cryptocurrency Exchanges and Software Wallets policy](https://support.google.com/googleplay/android-developer/answer/16329703?hl=en)
- [Frankfurt Kurnit: external purchase developments for Apple and Google](https://technologylaw.fkks.com/post/102mp7y/update-your-app-external-purchase-developments-for-apple-google)
- [Mondaq: US link-out status quo](https://www.mondaq.com/unitedstates/it-and-internet/1825852/update-your-app-external-purchase-developments-for-apple-google)

**Regulation**
- [Coin Center: FinCEN 2019 guidance on non-custodial services](https://coincenter.org/fincens-new-cryptocurrency-guidance-matches-coin-center-recommendations/)
- [crypto.news: FinCEN and the control test](https://crypto.news/us/fincen/)
- [Bitcoin Magazine: Samourai Wallet filing](https://bitcoinmagazine.com/news/filing-claims-u-s-prosecutors-knew-license-wasnt-required-for-samourai-wallet-prosecuted-them-anyways)
- [Troutman Pepper: CLARITY Act failure](https://www.troutman.com/insights/in-the-wake-of-clarity-acts-failure-agencies-move-forward-without-congressional-action-or-certainty/)
- [FinTech Weekly: CLARITY Act and GENIUS Act](https://www.fintechweekly.com/news/what-is-the-clarity-act-digital-asset-market-structure-explained-2026?variant=redesign)
- [TradeZero: PDT rule eliminated](https://tradezero.com/en-us/blog/how-intraday-margin-replaced-the-pattern-day-trading-rule)
- [Finovate: Coinbase RIA/CTA registration](https://finovate.com/coinbase-wants-to-become-your-primary-financial-platform/)

**Brokerage track**
- [Alpaca Broker API: integration setup](https://docs.alpaca.markets/docs/integration-setup-with-alpaca)
- [Alpaca integrates Kraken Embed (Crowdfund Insider)](https://www.crowdfundinsider.com/2025/06/242590-alpaca-integrates-kraken-embed-to-expand-crypto-access-for-partner-network/)
- [Zero Hash review 2026 (Stablecoin Insider)](https://stablecoininsider.org/zero-hash-review-2026-the-regulated-infrastructure-platform-behind-wall-streets-crypto-ambitions/)
- [BitGo Crypto-as-a-Service](https://www.bitgo.com/products/crypto-as-a-service)
- [Kraken Embed (Fortune)](https://fortune.com/crypto/2025/04/30/kraken-embed-service-fintechs-banks-crypto-trading/)
