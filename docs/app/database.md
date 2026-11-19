# Database

[← Hub](README.md) · [Technical](technical.md) · [Schema (SQL)](schema.sql)

## The short version

**One PostgreSQL database for the whole app, split into 12 schemas.** A schema is a named folder of tables inside the database, one folder per job (`auth`, `wallet`, `trading`, `ledger`...). So yes: separate tables for separate purposes, all in a single database.

**Why one database, not several:**
- A trade and its ledger entry must save together or not at all. That only works inside one database.
- One backup, one set of credentials to protect, one place for the security rules.
- The folders still keep things apart, and each service only gets the folders it needs.

**What lives outside it** (see [Technical: Data stores](technical.md#data-stores)): live prices and the signal stream in Redis, files and archives in S3, private keys with Privy, and our signing key in KMS.

**When to split later:** move price history to Timescale Cloud or ClickHouse if charts get slow, and add a read replica for reporting. Nothing else needs to move.

## The schemas

| Schema | What's in it | Tables |
|---|---|---|
| `auth` | Who the user is (login itself is Privy's job) | `users`, `identities`, `devices`, `sessions` |
| `app` | The user's settings and controls, plus shared helpers | `user_settings`, `user_limits`, `pauses`, `referral_codes`, `referrals` |
| `wallet` | Wallets and the auto-trading permission | `wallets`, `auto_trade_permissions`, `address_book`, `transfers` |
| `market` | Coins and price history | `tokens`, `candles` (partitioned by month) |
| `strategy` | Risk levels, our strategies, customer rules | `risk_levels`, `risk_level_tokens`, `strategies`, `strategy_versions`, `performance`, `model_account_daily`, `halts`, `enrollments`, `rules`, `rule_versions`, `rule_backtests` |
| `trading` | Everything about trades | `accounts`, `signals`, `orders`, `approvals`, `executions`, `recurring_buys`, `balances`, `reconciliation_runs`, `reconciliation_mismatches` |
| `ramp` | Cash in and out through Coinbase or MoonPay | `transactions`, `webhook_events` |
| `ledger` | The permanent record of every movement | `entries`, `tax_lots`, `tax_exports` |
| `billing` | App subscriptions | `plans`, `subscriptions`, `store_events`, view `current_plans` |
| `notify` | Push notifications and the inbox | `notifications`, `preferences`, `statements` |
| `ops` | Staff and platform switches | `staff`, `platform_controls` (kill switch), `incidents` |
| `audit` | Who did what, forever | `events` (partitioned by month), `signing_log` |

51 tables and one view in total. Every feature in [features.md](features.md) has a home; phase 2 features (referrals, rule backtests) are included so they don't need a redesign later.

**Checked:** the schema loads cleanly into PostgreSQL 16, and 27 spot checks pass. They cover user isolation, role limits, append-only records, duplicate signals and orders, permission limits, price protection, Face ID on sends and the required stop-loss. These are spot checks, not the full test suite below.

## Rules built into the database

These are enforced by Postgres itself, so a bug in our code can't break them.

**1. Each user sees only their own data.** Every customer table has a `user_id` and Row-Level Security. The App API verifies the Privy token, then runs `SET LOCAL app.user_id = '<uuid>'` at the start of each transaction. From then on, queries return and change only that user's rows. If the API forgets to set it, it sees nothing.

**2. Three service roles, each with only what it needs.**

| Role | Used by | Can do |
|---|---|---|
| `osprey_api` | App API | Read and write the signed-in user's rows. Read reference data (coins, strategies, plans). **Never deletes, never writes the ledger or audit trail, can't see** signals, webhooks, reconciliation or ops |
| `osprey_worker` | Trade router, rules service, chain watcher, webhook handlers | Work across all users. Ledger and audit tables are insert-only |
| `osprey_admin` | Admin dashboard | Read everything. Act only through specific tables: revoke permissions, halt strategies, pause users, flip platform switches |

**3. Nothing is deleted.** Rows change status instead: stopped, revoked, archived, closed. The only exception is `ledger.tax_lots`, which is rebuilt from the ledger.

**4. Permanent records can't be changed.** `ledger.entries`, `audit.events`, `audit.signing_log` and `strategy.rule_versions` reject every update, delete and truncate. Mistakes are fixed by adding a correcting row.

**5. A trade can't happen twice.**
- Each signal's sender ID is unique, so a repeated signal is ignored.
- There is one order per signal per account.
- Every order also carries a unique idempotency key.
- Partner webhooks are stored with unique event IDs, so a redelivered webhook does nothing.

**6. Money is stored exactly.** Token amounts are raw on-chain units (whole numbers, like the blockchain itself). Dollar amounts use fixed precision. No floating point anywhere money is involved.

**7. Demo mode uses the same tables.** Each user has a live account (their wallet) and a demo account (fake money). Demo trades run through the same orders and executions as real ones, as simulated fills. Tax exports and statements cover the live account only.

**8. Safety checks in the tables themselves:**
- A rule can't be saved without a stop-loss.
- An auto-trading permission can't last more than 90 days, and a wallet can have only one active permission at a time.
- An outgoing transfer can't be submitted without the user's Face ID confirmation, so auto-trading can never send money out.
- An approval can't be decided after it expires.
- A strategy version can't go live without an approval.
- A swap can't record receiving less than its price-protection minimum.
- A ledger entry must point to the trade, transfer or cash movement that caused it, and its sign must match its type.

**9. What we don't store:** passwords, private keys, card numbers, bank details or ID documents. Those stay with Privy and the ramp partners. Secrets live in AWS Secrets Manager and KMS.

## How a strategy trade moves through the tables

1. **Signal.** Nautilus decides "buy BTC" → a row in `trading.signals`, with the reason line and an expiry.
2. **Orders.** The trade router creates one row in `trading.orders` for each active enrollment, sized to that user's allocation and balance. Risk checks read:
   - `ops.platform_controls` (kill switch)
   - `app.pauses` (Pause everything, loss limit)
   - `app.user_limits`
   - `strategy.halts`
   - `strategy.risk_level_tokens` (allowed coins)
   - the active `wallet.auto_trade_permissions` row

   A failed check sets the order to `risk_rejected`, with the reason.
3. **Auto mode.** The router signs inside the permission. It writes a row to `trading.executions` (which permission signed it) and to `audit.signing_log`.
   **Approve mode.** The router writes a row to `trading.approvals` and a push to `notify.notifications`. The user approves or skips before it expires.
4. **Confirmation.** The chain watcher marks the execution confirmed. It then writes two `ledger.entries` (USDC out, BTC in), updates `trading.balances`, and sends the "Bought $100 of BTC: BTC dropped 6% today" notification.
5. **Reconciliation.** On a schedule, `trading.reconciliation_runs` compares the ledger with the chain. A mismatch adds a row to `trading.reconciliation_mismatches` and an `app.pauses` row that stops that user's auto-trading until it's resolved.

A customer rule works the same way, starting from a rule signal. A recurring buy or a manual trade starts at step 2.

## For the backend agent: building it

1. **Migrations.** Use Alembic (the API is FastAPI). Make [schema.sql](schema.sql) revision 0001 as raw SQL; every later change is a new revision. Never edit a deployed database by hand.
2. **Partitions.** Set up `pg_partman` (available on RDS) to create monthly partitions ahead of time for `market.candles` and `audit.events`. Choose a retention period for 1-minute candles.
3. **Coins.** Seed `market.tokens` and `strategy.risk_level_tokens` in a reviewed migration once the coin list is final. Check every contract address against the issuer's official docs (Circle for USDC, Coinbase for cbBTC).
4. **Connections.** The API must set `app.user_id` with `SET LOCAL` inside each transaction. That works with PgBouncer or RDS Proxy in transaction mode; plain `SET` does not.
5. **Archives.** Export `ledger.entries` and `audit.events` to S3 under Object Lock every night.
6. **Required tests** (money paths, per [Technical: Agent team rules](technical.md#agent-team-rules)):
   - **Isolation:** for every protected table, user A can't read, insert or update user B's rows, and the API with no `app.user_id` sees nothing
   - **Permissions:** the API role can't delete anything, can't insert into the ledger, and can't read signals, webhooks or audit tables
   - **Append-only:** update, delete and truncate fail on the ledger, audit, signing log and rule versions
   - **Duplicates:**
     - a repeated signal ID is rejected
     - a second order for the same signal and account is rejected
     - a redelivered webhook is ignored
   - **Auto-trading permission:**
     - a second active permission on one wallet is rejected
     - an expiry beyond 90 days is rejected
     - an execution can't use another user's permission
   - **Transfers:** an outgoing transfer can't be submitted without Face ID confirmation
   - **Ledger:** a wrong sign, a missing source, or a demo credit tied to a trade is rejected

## Decisions still open that touch the schema

- Subscription stores: in-app purchase only, or also web checkout (the `billing.subscriptions.store` values)
- Final coin list per risk level (seed data)
- Which ramp partner handles buying and which handles cashing out
- Plan names, prices and features (seed data)
- Which policy checks Privy enforces natively; anything it can't enforce is checked by the trade router before it signs

## Later, not in v1

- AI copilot conversations (phase 2)
- Leaderboard summary views, built from `strategy.performance` live rows
- More chains beyond Base: widen the `app.chain_id` list
- Trading from connected external wallets
- The brokerage track: partner-held accounts would be a new account kind in `trading.accounts`
