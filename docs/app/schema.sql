-- =====================================================================
-- Osprey application database: schema v1 (design)
--
-- PostgreSQL 16+ (Amazon RDS). One database, split into schemas by purpose.
-- Read database.md first. The backend agent turns this file into the first
-- migration with the project's migration tool; never hand-edit a deployed
-- database.
--
-- Conventions
--   * Every customer-owned row carries user_id and is protected by
--     Row-Level Security (RLS). The App API sees only the signed-in user.
--   * Nothing is deleted by the app. Rows change status instead
--     (stopped, revoked, archived, closed).
--   * The ledger, audit trail, signing log and rule versions are
--     append-only: updates and deletes raise an error.
--   * On-chain amounts are raw token units (integers, like the chain);
--     dollar amounts use app.usd.
--   * Addresses and transaction hashes are stored lowercase.
-- =====================================================================

BEGIN;

CREATE EXTENSION IF NOT EXISTS citext;   -- case-insensitive email addresses
-- gen_random_uuid() is built into PostgreSQL 13+.

-- ---------------------------------------------------------------------
-- Roles (group roles; infrastructure creates the login users)
--   osprey_api     App API. Customer-facing. Sees only the signed-in user's rows.
--   osprey_worker  Trade router, rules service, chain watcher, webhooks, schedulers.
--                  Works across users.
--   osprey_admin   Admin dashboard. Reads everything; can halt, pause and revoke.
-- The migration user owns all objects and is never used by a running service.
-- ---------------------------------------------------------------------
DO $$
DECLARE r text;
BEGIN
  FOREACH r IN ARRAY ARRAY['osprey_api', 'osprey_worker', 'osprey_admin'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = r) THEN
      EXECUTE format('CREATE ROLE %I NOLOGIN', r);
    END IF;
  END LOOP;
END $$;

-- ---------------------------------------------------------------------
-- Schemas
-- ---------------------------------------------------------------------
CREATE SCHEMA app;       -- shared types and helpers; user settings, limits, pauses, referrals
CREATE SCHEMA auth;      -- who the user is: account, login identities, devices, sessions
CREATE SCHEMA wallet;    -- wallets, auto-trading permissions, address book, transfers
CREATE SCHEMA market;    -- tokens and price history
CREATE SCHEMA strategy;  -- risk levels, our strategies, enrollments, customer rules
CREATE SCHEMA trading;   -- accounts, signals, orders, approvals, executions, balances, reconciliation
CREATE SCHEMA ramp;      -- cash in and cash out through ramp partners
CREATE SCHEMA ledger;    -- append-only record of every asset movement; tax lots and exports
CREATE SCHEMA billing;   -- plans and app subscriptions
CREATE SCHEMA notify;    -- notifications and inbox, preferences, statements
CREATE SCHEMA ops;       -- staff, platform controls (kill switch), incidents
CREATE SCHEMA audit;     -- append-only audit trail and signing log

-- ---------------------------------------------------------------------
-- Shared types and helpers
-- ---------------------------------------------------------------------
CREATE DOMAIN app.evm_address AS text CHECK (VALUE ~ '^0x[0-9a-f]{40}$');
CREATE DOMAIN app.tx_hash     AS text CHECK (VALUE ~ '^0x[0-9a-f]{64}$');
CREATE DOMAIN app.token_units AS numeric(78,0);   -- raw on-chain units; fits any uint256
CREATE DOMAIN app.usd         AS numeric(20,6);
CREATE DOMAIN app.chain_id    AS integer CHECK (VALUE IN (8453, 84532));  -- Base, Base Sepolia

CREATE FUNCTION app.current_user_id() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(current_setting('app.user_id', true), '')::uuid
$$;
COMMENT ON FUNCTION app.current_user_id() IS
  'The signed-in user. After verifying the Privy token, the App API runs '
  'SET LOCAL app.user_id = ''<uuid>'' at the start of every transaction.';

CREATE FUNCTION app.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END $$;

CREATE FUNCTION app.forbid_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  RAISE EXCEPTION '%.% is append-only: % is not allowed; add a correcting row instead',
    TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP;
END $$;

-- =====================================================================
-- ops: staff and platform controls
-- =====================================================================
CREATE TABLE ops.staff (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email       citext NOT NULL UNIQUE,
  name        text NOT NULL,
  role        text NOT NULL CHECK (role IN ('owner', 'admin', 'support', 'readonly')),
  active      boolean NOT NULL DEFAULT true,
  created_at  timestamptz NOT NULL DEFAULT now()
);
-- MFA is enforced by the staff login provider; nothing secret is stored here.

CREATE TABLE ops.platform_controls (
  key         text PRIMARY KEY,               -- 'kill_switch', 'auto_trading', 'new_signups', 'max_daily_volume_usd'
  enabled     boolean NOT NULL,
  value       jsonb,                          -- optional setting, e.g. {"usd": 250000}
  reason      text,
  changed_by  uuid REFERENCES ops.staff(id),
  changed_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE ops.incidents (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  title       text NOT NULL,
  severity    text NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
  status      text NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'mitigated', 'closed')),
  opened_by   uuid REFERENCES ops.staff(id),
  notes       text,
  opened_at   timestamptz NOT NULL DEFAULT now(),
  closed_at   timestamptz
);

-- =====================================================================
-- auth: who the user is
-- Login, passkeys and wallet keys live with Privy. We store no passwords
-- and no private keys.
-- =====================================================================
CREATE TABLE auth.users (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  privy_user_id  text NOT NULL UNIQUE,          -- Privy's user ID (did:privy:...)
  email          citext UNIQUE,
  status         text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended', 'closed')),
  country_code   char(2),
  region_code    text,                          -- US state; ramp partners' coverage differs by state
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now(),
  closed_at      timestamptz,
  CHECK ((status = 'closed') = (closed_at IS NOT NULL))
);

CREATE TABLE auth.identities (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      uuid NOT NULL REFERENCES auth.users(id),
  provider     text NOT NULL CHECK (provider IN ('email', 'apple', 'google', 'passkey')),
  subject      text NOT NULL,                   -- the provider's ID for this login, as reported by Privy
  email        citext,
  linked_at    timestamptz NOT NULL DEFAULT now(),
  unlinked_at  timestamptz,
  UNIQUE (provider, subject)
);
CREATE INDEX ON auth.identities (user_id);

CREATE TABLE auth.devices (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id        uuid NOT NULL REFERENCES auth.users(id),
  platform       text NOT NULL CHECK (platform IN ('ios', 'android')),
  push_token     text UNIQUE,                   -- Expo push token
  model          text,
  os_version     text,
  app_version    text,
  integrity_ok   boolean,                       -- false when jailbreak or root is detected
  first_seen_at  timestamptz NOT NULL DEFAULT now(),
  last_seen_at   timestamptz NOT NULL DEFAULT now(),
  revoked_at     timestamptz
);
CREATE INDEX ON auth.devices (user_id);

CREATE TABLE auth.sessions (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id         uuid NOT NULL REFERENCES auth.users(id),
  device_id       uuid REFERENCES auth.devices(id),
  ip              inet,
  created_at      timestamptz NOT NULL DEFAULT now(),
  last_active_at  timestamptz NOT NULL DEFAULT now(),
  revoked_at      timestamptz,                  -- remote session revoke
  revoked_reason  text
);
CREATE INDEX ON auth.sessions (user_id) WHERE revoked_at IS NULL;

-- Sign-up and sign-in: before app.user_id is set, RLS hides auth.users from
-- the API. This function finds or creates the user for a verified Privy ID.
-- Call it only after verifying the Privy token.
CREATE FUNCTION auth.user_id_for_privy(p_privy_user_id text, p_email citext DEFAULT NULL)
RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE uid uuid;
BEGIN
  INSERT INTO auth.users (privy_user_id, email)
  VALUES (p_privy_user_id, p_email)
  ON CONFLICT (privy_user_id) DO NOTHING;
  SELECT id INTO uid FROM auth.users WHERE privy_user_id = p_privy_user_id;
  RETURN uid;
END $$;
REVOKE ALL ON FUNCTION auth.user_id_for_privy(text, citext) FROM PUBLIC;

-- =====================================================================
-- market: tokens and prices
-- =====================================================================
CREATE TABLE market.tokens (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  chain_id          app.chain_id NOT NULL,
  symbol            text NOT NULL,              -- on-chain symbol, e.g. cbBTC
  display_symbol    text NOT NULL,              -- what users see, e.g. BTC
  name              text NOT NULL,
  contract_address  app.evm_address,            -- NULL only for the chain's native coin
  decimals          smallint NOT NULL CHECK (decimals BETWEEN 0 AND 36),
  is_stablecoin     boolean NOT NULL DEFAULT false,
  disclosure        text,                       -- e.g. 'cbBTC is backed 1:1 by bitcoin held by Coinbase'
  status            text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'delisted')),
  created_at        timestamptz NOT NULL DEFAULT now(),
  UNIQUE (chain_id, contract_address)
);
CREATE UNIQUE INDEX tokens_one_native_coin ON market.tokens (chain_id) WHERE contract_address IS NULL;
-- Token rows are added by a reviewed migration once the coin list is final.
-- Verify every contract address against the issuer's official docs first.

-- Price history in USD from exchange feeds. Partitioned by month: run
-- pg_partman (available on RDS) to create partitions ahead of time. The
-- default partition only catches stray rows.
CREATE TABLE market.candles (
  token_id   uuid NOT NULL REFERENCES market.tokens(id),
  bar_size   text NOT NULL CHECK (bar_size IN ('1m', '1h', '1d')),
  open_time  timestamptz NOT NULL,
  open       numeric(38,18) NOT NULL,
  high       numeric(38,18) NOT NULL,
  low        numeric(38,18) NOT NULL,
  close      numeric(38,18) NOT NULL,
  volume     numeric(38,18) NOT NULL DEFAULT 0,
  source     text NOT NULL,                     -- 'coinbase', 'kraken', ...
  PRIMARY KEY (token_id, bar_size, open_time),
  CHECK (low > 0 AND low <= LEAST(open, close) AND high >= GREATEST(open, close))
) PARTITION BY RANGE (open_time);
CREATE TABLE market.candles_default PARTITION OF market.candles DEFAULT;

-- =====================================================================
-- strategy (part 1): risk levels and our strategies
-- =====================================================================
CREATE TABLE strategy.risk_levels (
  code                     text PRIMARY KEY CHECK (code IN ('steady', 'balanced', 'bold')),
  name                     text NOT NULL,
  sort_order               smallint NOT NULL UNIQUE,
  summary                  text NOT NULL,
  max_drawdown_budget_pct  numeric(5,2),        -- set by the risk officer from Monte Carlo; NULL until then
  min_cash_pct             numeric(5,2),
  max_coin_pct             numeric(5,2),
  stop_loss_required       boolean NOT NULL DEFAULT false,
  updated_at               timestamptz NOT NULL DEFAULT now()
);

-- Coin allowlist per risk level. History is kept: a removed coin gets
-- removed_at instead of being deleted.
CREATE TABLE strategy.risk_level_tokens (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  risk_level      text NOT NULL REFERENCES strategy.risk_levels(code),
  token_id        uuid NOT NULL REFERENCES market.tokens(id),
  max_weight_pct  numeric(5,2),
  approved_by     uuid REFERENCES ops.staff(id),
  added_at        timestamptz NOT NULL DEFAULT now(),
  removed_at      timestamptz
);
CREATE UNIQUE INDEX risk_level_tokens_active ON strategy.risk_level_tokens (risk_level, token_id)
  WHERE removed_at IS NULL;

CREATE TABLE strategy.strategies (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug         text NOT NULL UNIQUE,            -- e.g. 'dip-buy-balanced'
  name         text NOT NULL,
  risk_level   text NOT NULL REFERENCES strategy.risk_levels(code),
  summary      text NOT NULL,                   -- plain-English strategy card text
  description  text,
  status       text NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'paper', 'live', 'halted', 'retired')),
  created_at   timestamptz NOT NULL DEFAULT now(),
  updated_at   timestamptz NOT NULL DEFAULT now()
);

-- Pinned, approved configurations exported from the Strategy Lab
-- (exports/<name>/config.yaml). Only one is current per strategy.
CREATE TABLE strategy.strategy_versions (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id    uuid NOT NULL REFERENCES strategy.strategies(id),
  version        integer NOT NULL CHECK (version > 0),
  config         jsonb NOT NULL,
  code_commit    text NOT NULL,
  data_snapshot  text,
  audit_report   text,                          -- link to the backtest-auditor report
  approved_by    uuid REFERENCES ops.staff(id),
  approved_at    timestamptz,
  is_current     boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (strategy_id, version),
  CHECK (NOT is_current OR approved_at IS NOT NULL)
);
CREATE UNIQUE INDEX strategy_versions_one_current ON strategy.strategy_versions (strategy_id)
  WHERE is_current;

-- Numbers on strategy cards. Backtest and live results are separate rows;
-- the app always labels backtests hypothetical. The leaderboard uses live only.
CREATE TABLE strategy.performance (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_version_id  uuid NOT NULL REFERENCES strategy.strategy_versions(id),
  kind                 text NOT NULL CHECK (kind IN ('backtest', 'live')),
  period_start         date NOT NULL,
  period_end           date NOT NULL,
  total_return_pct     numeric(10,4),
  annual_sharpe        numeric(8,4),
  max_drawdown_pct     numeric(7,4),
  worst_losing_streak  integer,
  trades               integer,
  details              jsonb NOT NULL DEFAULT '{}',
  computed_at          timestamptz NOT NULL DEFAULT now(),
  CHECK (period_end >= period_start)
);
CREATE INDEX ON strategy.performance (strategy_version_id, kind);

-- Daily equity of each strategy's paper model account: its live track record.
CREATE TABLE strategy.model_account_daily (
  strategy_id  uuid NOT NULL REFERENCES strategy.strategies(id),
  day          date NOT NULL,
  equity_usd   app.usd NOT NULL,
  cash_usd     app.usd NOT NULL,
  positions    jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (strategy_id, day)
);

CREATE TABLE strategy.halts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  strategy_id  uuid NOT NULL REFERENCES strategy.strategies(id),
  reason       text NOT NULL,
  halted_by    text NOT NULL CHECK (halted_by IN ('auto', 'staff', 'kill_switch')),
  staff_id     uuid REFERENCES ops.staff(id),
  halted_at    timestamptz NOT NULL DEFAULT now(),
  resumed_at   timestamptz,
  resumed_by   uuid REFERENCES ops.staff(id)
);
CREATE UNIQUE INDEX halts_one_open ON strategy.halts (strategy_id) WHERE resumed_at IS NULL;

-- =====================================================================
-- app: the user's settings, limits and pauses
-- =====================================================================
CREATE TABLE app.user_settings (
  user_id               uuid PRIMARY KEY REFERENCES auth.users(id),
  risk_level            text REFERENCES strategy.risk_levels(code),   -- chosen by the user; NULL until chosen
  risk_level_chosen_at  timestamptz,
  demo_mode             boolean NOT NULL DEFAULT false,               -- app shows the demo account
  timezone              text NOT NULL DEFAULT 'UTC',
  locale                text NOT NULL DEFAULT 'en-US',
  updated_at            timestamptz NOT NULL DEFAULT now(),
  CHECK ((risk_level IS NULL) = (risk_level_chosen_at IS NULL))
);

-- Personal limits. Also copied into each auto-trading permission, where the
-- wallet provider enforces them.
CREATE TABLE app.user_limits (
  user_id            uuid PRIMARY KEY REFERENCES auth.users(id),
  max_per_trade_usd  app.usd NOT NULL CHECK (max_per_trade_usd > 0),
  max_per_day_usd    app.usd NOT NULL,
  slippage_bps       integer NOT NULL DEFAULT 100 CHECK (slippage_bps BETWEEN 1 AND 500),
  loss_limit_pct     numeric(5,2) CHECK (loss_limit_pct > 0 AND loss_limit_pct <= 100),
  loss_limit_window  text CHECK (loss_limit_window IN ('day', 'week')),
  updated_at         timestamptz NOT NULL DEFAULT now(),
  CHECK (max_per_day_usd >= max_per_trade_usd),
  CHECK ((loss_limit_pct IS NULL) = (loss_limit_window IS NULL))
);

-- An open pause (ended_at IS NULL) stops all of the user's trading. The
-- trade router checks this before every order.
CREATE TABLE app.pauses (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users(id),
  kind        text NOT NULL CHECK (kind IN ('pause_everything', 'loss_limit', 'reconciliation', 'admin')),
  reason      text,
  started_by  text NOT NULL CHECK (started_by IN ('user', 'system', 'staff')),
  staff_id    uuid REFERENCES ops.staff(id),
  started_at  timestamptz NOT NULL DEFAULT now(),
  ended_at    timestamptz
);
CREATE UNIQUE INDEX pauses_one_open_per_kind ON app.pauses (user_id, kind) WHERE ended_at IS NULL;

-- Phase 2: referral program.
CREATE TABLE app.referral_codes (
  user_id     uuid PRIMARY KEY REFERENCES auth.users(id),
  code        text NOT NULL UNIQUE,
  created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE app.referrals (
  referred_user_id  uuid PRIMARY KEY REFERENCES auth.users(id),
  user_id           uuid NOT NULL REFERENCES auth.users(id),   -- the referrer (owner of the row)
  created_at        timestamptz NOT NULL DEFAULT now(),
  rewarded_at       timestamptz,
  CHECK (referred_user_id <> user_id)
);

-- =====================================================================
-- wallet: wallets and the auto-trading permission
-- =====================================================================
CREATE TABLE wallet.wallets (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid NOT NULL REFERENCES auth.users(id),
  chain_id         app.chain_id NOT NULL,
  address          app.evm_address NOT NULL,
  kind             text NOT NULL CHECK (kind IN ('smart', 'embedded', 'external')),
                   -- smart: the ERC-4337 wallet the app trades from
                   -- embedded: the Privy wallet that owns it
                   -- external: a connected wallet (phase 2)
  privy_wallet_id  text UNIQUE,
  is_primary       boolean NOT NULL DEFAULT false,
  created_at       timestamptz NOT NULL DEFAULT now(),
  exported_at      timestamptz,                 -- the user exported the wallet to take it elsewhere
  UNIQUE (chain_id, address),
  UNIQUE (id, user_id)
);
CREATE UNIQUE INDEX wallets_one_primary ON wallet.wallets (user_id, chain_id) WHERE is_primary;

-- Our server's signer on the user's wallet, limited by a policy that Privy
-- enforces. One active permission per wallet; each renewal is a new version.
CREATE TABLE wallet.auto_trade_permissions (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL,
  wallet_id          uuid NOT NULL,
  version            integer NOT NULL CHECK (version > 0),
  status             text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'active', 'expired', 'revoked', 'failed')),
  privy_signer_id    text,
  privy_policy_id    text,
  policy             jsonb NOT NULL,              -- exact policy sent to Privy: contracts, tokens, caps, destination, expiry
  allowed_token_ids  uuid[] NOT NULL,             -- the risk level's allowlist at grant time
  max_per_trade_usd  app.usd NOT NULL CHECK (max_per_trade_usd > 0),
  max_per_day_usd    app.usd NOT NULL,
  granted_at         timestamptz,                 -- the user confirmed with Face ID
  expires_at         timestamptz NOT NULL,
  revoked_at         timestamptz,
  revoked_by         text CHECK (revoked_by IN ('user', 'pause_everything', 'staff', 'kill_switch', 'system')),
  revoke_reason      text,
  created_at         timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (wallet_id, user_id) REFERENCES wallet.wallets (id, user_id),
  UNIQUE (wallet_id, version),
  UNIQUE (id, user_id),
  CHECK (max_per_day_usd >= max_per_trade_usd),
  CHECK (status <> 'active' OR granted_at IS NOT NULL),
  CHECK (granted_at IS NULL OR expires_at <= granted_at + interval '90 days'),
  CHECK ((status = 'revoked') = (revoked_at IS NOT NULL)),
  CHECK ((revoked_at IS NULL) = (revoked_by IS NULL))
);
CREATE UNIQUE INDEX permissions_one_active ON wallet.auto_trade_permissions (wallet_id)
  WHERE status = 'active';
CREATE INDEX ON wallet.auto_trade_permissions (expires_at) WHERE status = 'active';

CREATE TABLE wallet.address_book (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES auth.users(id),
  chain_id      app.chain_id NOT NULL,
  address       app.evm_address NOT NULL,
  label         text NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  last_used_at  timestamptz,
  UNIQUE (user_id, chain_id, address)
);

-- =====================================================================
-- trading (part 1): accounts
-- A user has one live account (their wallet) and one demo account (fake
-- money). Everything that trades points at an account, so demo mode uses
-- the same tables and code paths as real money.
-- =====================================================================
CREATE TABLE trading.accounts (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users(id),
  kind        text NOT NULL CHECK (kind IN ('live', 'demo')),
  wallet_id   uuid,
  created_at  timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (wallet_id, user_id) REFERENCES wallet.wallets (id, user_id),
  CHECK ((kind = 'live') = (wallet_id IS NOT NULL)),
  UNIQUE (id, user_id)
);
CREATE UNIQUE INDEX accounts_one_demo ON trading.accounts (user_id) WHERE kind = 'demo';
CREATE UNIQUE INDEX accounts_one_per_wallet ON trading.accounts (wallet_id) WHERE wallet_id IS NOT NULL;

-- Sends and receives of crypto, including the cash-out send to a ramp
-- partner. Every outgoing transfer is confirmed by the user with Face ID;
-- auto-trading can never send money out.
CREATE TABLE wallet.transfers (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL,
  account_id         uuid NOT NULL,
  direction          text NOT NULL CHECK (direction IN ('in', 'out')),
  purpose            text NOT NULL CHECK (purpose IN ('send', 'receive', 'cash_out')),
  token_id           uuid NOT NULL REFERENCES market.tokens(id),
  amount_units       app.token_units NOT NULL CHECK (amount_units > 0),
  counterparty       app.evm_address NOT NULL,      -- recipient for sends, sender for receives
  new_address        boolean NOT NULL DEFAULT false,  -- first send to this address; the app warned
  status             text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'submitted', 'confirmed', 'failed')),
  user_confirmed_at  timestamptz,                   -- Face ID confirmation
  tx_hash            app.tx_hash,
  block_number       bigint,
  created_at         timestamptz NOT NULL DEFAULT now(),
  confirmed_at       timestamptz,
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  UNIQUE (tx_hash, token_id),
  CHECK ((purpose = 'receive') = (direction = 'in')),
  CHECK (direction = 'in' OR status = 'pending' OR user_confirmed_at IS NOT NULL)
);
CREATE INDEX ON wallet.transfers (user_id, created_at DESC);

-- =====================================================================
-- strategy (part 2): enrollments and customer rules
-- =====================================================================

-- A user following one of our strategies.
CREATE TABLE strategy.enrollments (
  id                        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                   uuid NOT NULL,
  account_id                uuid NOT NULL,
  strategy_id               uuid NOT NULL REFERENCES strategy.strategies(id),
  mode                      text NOT NULL CHECK (mode IN ('auto', 'approve')),
  allocation_usd            app.usd NOT NULL CHECK (allocation_usd > 0),
  status                    text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'stopped')),
  above_level_confirmed_at  timestamptz,           -- confirmed the warning for a strategy above their risk level
  started_at                timestamptz NOT NULL DEFAULT now(),
  paused_at                 timestamptz,
  stopped_at                timestamptz,
  updated_at                timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  UNIQUE (id, user_id),
  CHECK ((status = 'stopped') = (stopped_at IS NOT NULL))
);
CREATE UNIQUE INDEX enrollments_one_open ON strategy.enrollments (account_id, strategy_id)
  WHERE status <> 'stopped';
CREATE INDEX ON strategy.enrollments (strategy_id) WHERE status = 'active';

-- Customer rules: stored as data, never code. The rule row holds what can
-- change at any time (name, mode, status); each edit to the logic creates
-- a new, immutable row in rule_versions.
CREATE TABLE strategy.rules (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          uuid NOT NULL,
  account_id       uuid NOT NULL,
  name             text NOT NULL,
  mode             text NOT NULL CHECK (mode IN ('auto', 'approve')),
  status           text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'archived')),
  current_version  integer NOT NULL DEFAULT 1 CHECK (current_version > 0),
  last_fired_at    timestamptz,
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  UNIQUE (id, user_id)
);
CREATE INDEX ON strategy.rules (user_id) WHERE status = 'active';

CREATE TABLE strategy.rule_versions (
  rule_id            uuid NOT NULL,
  version            integer NOT NULL CHECK (version > 0),
  user_id            uuid NOT NULL,
  token_id           uuid NOT NULL REFERENCES market.tokens(id),
  definition         jsonb NOT NULL,              -- the validated rule record: conditions and action
  schema_version     smallint NOT NULL DEFAULT 1,
  stop_loss_pct      numeric(5,2) NOT NULL CHECK (stop_loss_pct > 0 AND stop_loss_pct < 100),  -- required
  take_profit_pct    numeric(6,2) CHECK (take_profit_pct > 0),
  max_runs_per_week  smallint NOT NULL DEFAULT 1 CHECK (max_runs_per_week BETWEEN 1 AND 50),
  created_via        text NOT NULL DEFAULT 'app' CHECK (created_via IN ('app', 'copilot')),
  created_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (rule_id, version),
  FOREIGN KEY (rule_id, user_id) REFERENCES strategy.rules (id, user_id)
);
CREATE INDEX ON strategy.rule_versions (token_id);

-- Phase 2: rule backtests. Only results are stored, always labeled hypothetical.
CREATE TABLE strategy.rule_backtests (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES auth.users(id),
  rule_id       uuid NOT NULL,
  rule_version  integer NOT NULL,
  status        text NOT NULL DEFAULT 'queued' CHECK (status IN ('queued', 'running', 'done', 'failed')),
  period_start  date NOT NULL,
  period_end    date NOT NULL,
  results       jsonb,                            -- summary numbers; the full result file is in S3
  results_uri   text,
  requested_at  timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  FOREIGN KEY (rule_id, rule_version) REFERENCES strategy.rule_versions (rule_id, version),
  CHECK (period_end > period_start)
);

-- =====================================================================
-- trading (part 2): from signal to settled trade
-- =====================================================================

-- A decision from a strategy node (NautilusTrader) or the rules service.
-- external_id is the sender's unique ID, so a repeated signal is ignored.
CREATE TABLE trading.signals (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  external_id          text NOT NULL UNIQUE,
  source               text NOT NULL CHECK (source IN ('strategy', 'rule')),
  strategy_version_id  uuid REFERENCES strategy.strategy_versions(id),
  rule_id              uuid,
  rule_version         integer,
  user_id              uuid REFERENCES auth.users(id),   -- set for rule signals: a rule belongs to one user
  token_id             uuid NOT NULL REFERENCES market.tokens(id),
  side                 text NOT NULL CHECK (side IN ('buy', 'sell')),
  target_weight        numeric(7,6) CHECK (target_weight BETWEEN 0 AND 1),  -- strategy: target share of the allocation
  amount_usd           app.usd CHECK (amount_usd > 0),                      -- rule: the rule's action amount
  reason               text NOT NULL,             -- the plain-English "why"
  price_at_decision    numeric(38,18) NOT NULL CHECK (price_at_decision > 0),
  created_at           timestamptz NOT NULL,
  expires_at           timestamptz NOT NULL,
  received_at          timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (rule_id, rule_version) REFERENCES strategy.rule_versions (rule_id, version),
  CHECK (expires_at > created_at),
  CHECK (
    (source = 'strategy' AND strategy_version_id IS NOT NULL AND target_weight IS NOT NULL
       AND rule_id IS NULL AND user_id IS NULL)
    OR
    (source = 'rule' AND rule_id IS NOT NULL AND rule_version IS NOT NULL AND user_id IS NOT NULL
       AND strategy_version_id IS NULL)
  )
);
CREATE INDEX ON trading.signals (created_at);

CREATE TABLE trading.recurring_buys (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL,
  account_id    uuid NOT NULL,
  token_id      uuid NOT NULL REFERENCES market.tokens(id),
  amount_usd    app.usd NOT NULL CHECK (amount_usd > 0),
  cadence       text NOT NULL CHECK (cadence IN ('daily', 'weekly', 'biweekly', 'monthly')),
  day_of_week   smallint CHECK (day_of_week BETWEEN 0 AND 6),     -- 0 = Sunday
  day_of_month  smallint CHECK (day_of_month BETWEEN 1 AND 28),
  mode          text NOT NULL CHECK (mode IN ('auto', 'approve')),
  status        text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'cancelled')),
  next_run_at   timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  CHECK ((cadence IN ('weekly', 'biweekly')) = (day_of_week IS NOT NULL)),
  CHECK ((cadence = 'monthly') = (day_of_month IS NOT NULL))
);
CREATE INDEX ON trading.recurring_buys (next_run_at) WHERE status = 'active';

-- One trade for one account: from a signal (fanned out per subscriber), a
-- rule, a recurring buy, or a manual buy or sell.
CREATE TABLE trading.orders (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id               uuid NOT NULL,
  account_id            uuid NOT NULL,
  origin                text NOT NULL CHECK (origin IN ('strategy', 'rule', 'recurring', 'manual')),
  mode                  text NOT NULL CHECK (mode IN ('auto', 'approve', 'manual')),
  signal_id             uuid REFERENCES trading.signals(id),
  enrollment_id         uuid REFERENCES strategy.enrollments(id),
  rule_id               uuid,
  rule_version          integer,
  recurring_buy_id      uuid REFERENCES trading.recurring_buys(id),
  sell_token_id         uuid NOT NULL REFERENCES market.tokens(id),
  buy_token_id          uuid NOT NULL REFERENCES market.tokens(id),
  sell_amount_units     app.token_units NOT NULL CHECK (sell_amount_units > 0),
  min_buy_amount_units  app.token_units CHECK (min_buy_amount_units > 0),   -- price protection
  notional_usd          app.usd NOT NULL CHECK (notional_usd > 0),
  slippage_bps          integer NOT NULL CHECK (slippage_bps BETWEEN 1 AND 500),
  reason                text NOT NULL,              -- shown on every trade
  status                text NOT NULL DEFAULT 'created' CHECK (status IN (
                          'created', 'risk_rejected', 'awaiting_approval', 'approved', 'skipped',
                          'expired', 'submitted', 'filled', 'failed', 'cancelled')),
  reject_reason         text,                       -- which risk check said no
  idempotency_key       text NOT NULL UNIQUE,
  expires_at            timestamptz,
  created_at            timestamptz NOT NULL DEFAULT now(),
  updated_at            timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  FOREIGN KEY (rule_id, rule_version) REFERENCES strategy.rule_versions (rule_id, version),
  UNIQUE (signal_id, account_id),     -- one trade per signal per account: a retry can never double-buy
  UNIQUE (id, user_id),
  CHECK (sell_token_id <> buy_token_id),
  CHECK ((origin IN ('strategy', 'rule')) = (signal_id IS NOT NULL)),
  CHECK ((origin = 'strategy') = (enrollment_id IS NOT NULL)),
  CHECK ((origin = 'rule') = (rule_id IS NOT NULL AND rule_version IS NOT NULL)),
  CHECK ((origin = 'recurring') = (recurring_buy_id IS NOT NULL)),
  CHECK ((origin = 'manual') = (mode = 'manual')),
  CHECK (status <> 'risk_rejected' OR reject_reason IS NOT NULL),
  CHECK (mode <> 'approve' OR expires_at IS NOT NULL)
);
CREATE INDEX ON trading.orders (user_id, created_at DESC);
CREATE INDEX ON trading.orders (account_id, created_at) WHERE status IN ('submitted', 'filled');
CREATE INDEX ON trading.orders (status, expires_at) WHERE status = 'awaiting_approval';

-- Approve mode: the push, and the user's decision. A decision can't come
-- after the approval expired.
CREATE TABLE trading.approvals (
  order_id      uuid PRIMARY KEY,
  user_id       uuid NOT NULL,
  push_sent_at  timestamptz,
  expires_at    timestamptz NOT NULL,
  decision      text CHECK (decision IN ('approved', 'skipped')),
  decided_at    timestamptz,
  device_id     uuid REFERENCES auth.devices(id),
  FOREIGN KEY (order_id, user_id) REFERENCES trading.orders (id, user_id),
  CHECK ((decision IS NULL) = (decided_at IS NULL)),
  CHECK (decided_at IS NULL OR decided_at <= expires_at)
);

-- How an order was carried out: an on-chain swap through 0x, or a
-- simulated fill for a demo account. A failed attempt can be retried
-- (attempt 2, 3...) only inside the signal's time window.
CREATE TABLE trading.executions (
  id                    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id              uuid NOT NULL,
  user_id               uuid NOT NULL,
  attempt               smallint NOT NULL DEFAULT 1 CHECK (attempt BETWEEN 1 AND 5),
  kind                  text NOT NULL CHECK (kind IN ('onchain', 'simulated')),
  signed_by             text CHECK (signed_by IN ('permission', 'user')),
  permission_id         uuid,                       -- the auto-trading permission used
  chain_id              app.chain_id,
  tx_hash               app.tx_hash UNIQUE,
  user_op_hash          app.tx_hash,               -- ERC-4337 user operation
  quote_id              text,                       -- 0x quote reference
  sell_amount_units     app.token_units NOT NULL CHECK (sell_amount_units > 0),
  min_buy_amount_units  app.token_units,
  buy_amount_units      app.token_units,           -- actually received; set on confirmation
  price_usd             numeric(38,18),            -- effective price of the bought token
  gas_used              bigint,
  gas_cost_usd          app.usd,                    -- sponsored by us; tracked per trade
  status                text NOT NULL DEFAULT 'submitted' CHECK (status IN ('submitted', 'confirmed', 'reverted', 'dropped')),
  error                 text,
  block_number          bigint,
  submitted_at          timestamptz NOT NULL DEFAULT now(),
  confirmed_at          timestamptz,
  FOREIGN KEY (order_id, user_id) REFERENCES trading.orders (id, user_id),
  FOREIGN KEY (permission_id, user_id) REFERENCES wallet.auto_trade_permissions (id, user_id),
  UNIQUE (order_id, attempt),
  CHECK ((kind = 'onchain') = (chain_id IS NOT NULL AND signed_by IS NOT NULL)),
  CHECK (kind = 'onchain' OR (tx_hash IS NULL AND permission_id IS NULL)),
  CHECK (signed_by IS DISTINCT FROM 'permission' OR permission_id IS NOT NULL),
  CHECK (status <> 'confirmed' OR buy_amount_units IS NOT NULL),
  CHECK (buy_amount_units IS NULL OR min_buy_amount_units IS NULL OR buy_amount_units >= min_buy_amount_units)
);
CREATE INDEX ON trading.executions (status) WHERE status = 'submitted';

-- Current holdings. Live accounts: a cache of what the chain says (the chain
-- is the source of truth). Demo accounts: the simulated balance itself.
CREATE TABLE trading.balances (
  account_id    uuid NOT NULL,
  token_id      uuid NOT NULL REFERENCES market.tokens(id),
  user_id       uuid NOT NULL,
  amount_units  app.token_units NOT NULL CHECK (amount_units >= 0),
  as_of_block   bigint,
  updated_at    timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (account_id, token_id),
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id)
);

-- =====================================================================
-- ramp: cash in and out through Coinbase or MoonPay.
-- No card, bank or ID-document data is stored; it stays with the partner.
-- =====================================================================
CREATE TABLE ramp.transactions (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id             uuid NOT NULL,
  account_id          uuid NOT NULL,               -- always the live account
  provider            text NOT NULL CHECK (provider IN ('coinbase', 'moonpay')),
  direction           text NOT NULL CHECK (direction IN ('buy', 'sell')),   -- buy = add cash, sell = cash out
  provider_ref        text,                        -- the partner's session or transaction ID
  status              text NOT NULL DEFAULT 'created'
                      CHECK (status IN ('created', 'pending', 'completed', 'failed', 'cancelled', 'expired')),
  fiat_currency       char(3) NOT NULL DEFAULT 'USD',
  fiat_amount         numeric(18,2) CHECK (fiat_amount > 0),
  partner_fee_fiat    numeric(18,2) CHECK (partner_fee_fiat >= 0),
  token_id            uuid NOT NULL REFERENCES market.tokens(id),
  token_amount_units  app.token_units CHECK (token_amount_units > 0),
  deposit_address     app.evm_address,             -- cash out: where the user sends USDC
  transfer_id         uuid REFERENCES wallet.transfers(id),   -- cash out: the user's Face ID-confirmed send
  tx_hash             app.tx_hash,                 -- cash in: the partner's delivery to the wallet
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  completed_at        timestamptz,
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  UNIQUE (provider, provider_ref),
  CHECK (direction = 'buy' OR transfer_id IS NOT NULL OR status IN ('created', 'cancelled', 'expired')),
  CHECK ((status = 'completed') = (completed_at IS NOT NULL))
);
CREATE INDEX ON ramp.transactions (user_id, created_at DESC);

-- Raw partner webhooks, stored before processing. The unique key makes a
-- redelivered webhook harmless.
CREATE TABLE ramp.webhook_events (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  provider      text NOT NULL CHECK (provider IN ('coinbase', 'moonpay')),
  event_id      text NOT NULL,
  event_type    text,
  payload       jsonb NOT NULL,
  received_at   timestamptz NOT NULL DEFAULT now(),
  processed_at  timestamptz,
  error         text,
  UNIQUE (provider, event_id)
);

-- =====================================================================
-- ledger: every asset movement, append-only. Corrections are new rows.
-- Mirrors the chain; the source for history, statements and tax exports.
-- =====================================================================
CREATE TABLE ledger.entries (
  id                   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  user_id              uuid NOT NULL,
  account_id           uuid NOT NULL,
  token_id             uuid NOT NULL REFERENCES market.tokens(id),
  amount_units         app.token_units NOT NULL CHECK (amount_units <> 0),   -- positive in, negative out
  kind                 text NOT NULL CHECK (kind IN (
                         'swap_in', 'swap_out', 'cash_in', 'cash_out',
                         'transfer_in', 'transfer_out', 'demo_credit', 'correction')),
  usd_price            numeric(38,18),             -- token price at the time; tax cost basis
  usd_value            app.usd,
  execution_id         uuid REFERENCES trading.executions(id),   -- swap_in, swap_out
  transfer_id          uuid REFERENCES wallet.transfers(id),     -- transfer_in, transfer_out, cash_out
  ramp_transaction_id  uuid REFERENCES ramp.transactions(id),    -- cash_in
  corrects_entry_id    bigint REFERENCES ledger.entries(id),     -- correction
  tx_hash              app.tx_hash,
  block_number         bigint,
  occurred_at          timestamptz NOT NULL,       -- block time (or simulated time for demo)
  recorded_at          timestamptz NOT NULL DEFAULT now(),
  note                 text,
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  CHECK (kind = 'correction'
         OR sign(amount_units) = CASE WHEN kind IN ('swap_in', 'cash_in', 'transfer_in', 'demo_credit')
                                      THEN 1 ELSE -1 END),
  CHECK (CASE kind
           WHEN 'demo_credit' THEN num_nonnulls(execution_id, transfer_id, ramp_transaction_id, corrects_entry_id) = 0
           ELSE num_nonnulls(execution_id, transfer_id, ramp_transaction_id, corrects_entry_id) = 1
         END),
  CHECK (kind NOT IN ('swap_in', 'swap_out') OR execution_id IS NOT NULL),
  CHECK (kind NOT IN ('transfer_in', 'transfer_out', 'cash_out') OR transfer_id IS NOT NULL),
  CHECK (kind <> 'cash_in' OR ramp_transaction_id IS NOT NULL),
  CHECK (kind <> 'correction' OR corrects_entry_id IS NOT NULL)
);
CREATE INDEX ON ledger.entries (user_id, occurred_at);
CREATE INDEX ON ledger.entries (account_id, token_id, occurred_at);

-- Cost-basis lots (first in, first out), rebuilt from ledger.entries. Derived
-- data: safe to delete and rebuild.
CREATE TABLE ledger.tax_lots (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id            uuid NOT NULL,
  account_id         uuid NOT NULL,
  token_id           uuid NOT NULL REFERENCES market.tokens(id),
  acquired_entry_id  bigint NOT NULL UNIQUE REFERENCES ledger.entries(id),
  acquired_at        timestamptz NOT NULL,
  quantity_units     app.token_units NOT NULL CHECK (quantity_units > 0),
  remaining_units    app.token_units NOT NULL,
  cost_basis_usd     app.usd NOT NULL CHECK (cost_basis_usd >= 0),
  method             text NOT NULL DEFAULT 'fifo' CHECK (method IN ('fifo')),
  rebuilt_at         timestamptz NOT NULL DEFAULT now(),
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  CHECK (remaining_units >= 0 AND remaining_units <= quantity_units)
);

-- Tax export files the user downloaded.
CREATE TABLE ledger.tax_exports (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users(id),
  tax_year    smallint NOT NULL CHECK (tax_year >= 2024),
  format      text NOT NULL CHECK (format IN ('csv', 'pdf')),
  file_uri    text NOT NULL,
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- =====================================================================
-- billing: app subscriptions (in-app purchase or web checkout)
-- =====================================================================
CREATE TABLE billing.plans (
  code      text PRIMARY KEY,
  name      text NOT NULL,
  features  jsonb NOT NULL DEFAULT '{}',          -- e.g. {"auto_trading": true, "advanced_rules": false}
  active    boolean NOT NULL DEFAULT true
);

CREATE TABLE billing.subscriptions (
  id                     uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id                uuid NOT NULL REFERENCES auth.users(id),
  plan_code              text NOT NULL REFERENCES billing.plans(code),
  store                  text NOT NULL CHECK (store IN ('apple', 'google', 'web')),
  store_subscription_id  text NOT NULL,           -- Apple original transaction ID, Google purchase token, or web subscription ID
  status                 text NOT NULL CHECK (status IN (
                           'trialing', 'active', 'grace_period', 'past_due', 'cancelled', 'expired')),
  current_period_end     timestamptz,
  auto_renew             boolean NOT NULL DEFAULT true,
  created_at             timestamptz NOT NULL DEFAULT now(),
  updated_at             timestamptz NOT NULL DEFAULT now(),
  UNIQUE (store, store_subscription_id)
);
CREATE INDEX ON billing.subscriptions (user_id);

CREATE TABLE billing.store_events (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  store         text NOT NULL CHECK (store IN ('apple', 'google', 'web')),
  event_id      text NOT NULL,
  event_type    text,
  payload       jsonb NOT NULL,
  received_at   timestamptz NOT NULL DEFAULT now(),
  processed_at  timestamptz,
  error         text,
  UNIQUE (store, event_id)
);

-- The plan each user is on right now (users without a row are on 'free').
CREATE VIEW billing.current_plans WITH (security_invoker = true) AS
SELECT DISTINCT ON (user_id) user_id, plan_code, status, current_period_end
FROM billing.subscriptions
WHERE status IN ('trialing', 'active', 'grace_period')
ORDER BY user_id, current_period_end DESC NULLS LAST;

-- =====================================================================
-- notify: push notifications and the in-app inbox (one table), preferences,
-- monthly statements
-- =====================================================================
CREATE TABLE notify.notifications (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES auth.users(id),
  kind          text NOT NULL CHECK (kind IN (
                  'trade_executed', 'approval_needed', 'limit_hit', 'strategy_paused', 'cash_status',
                  'permission_expiring', 'weekly_recap', 'security', 'system')),
  title         text NOT NULL,
  body          text NOT NULL,
  data          jsonb NOT NULL DEFAULT '{}',      -- deep-link targets, e.g. {"order_id": "..."}
  push_status   text NOT NULL DEFAULT 'pending' CHECK (push_status IN ('pending', 'sent', 'failed', 'not_sent')),
  push_sent_at  timestamptz,
  read_at       timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX ON notify.notifications (user_id, created_at DESC);
CREATE INDEX ON notify.notifications (created_at) WHERE push_status = 'pending';

CREATE TABLE notify.preferences (
  user_id           uuid PRIMARY KEY REFERENCES auth.users(id),
  push_enabled      boolean NOT NULL DEFAULT true,
  weekly_recap      boolean NOT NULL DEFAULT true,
  email_statements  boolean NOT NULL DEFAULT true,
  marketing         boolean NOT NULL DEFAULT false,
  updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE notify.statements (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES auth.users(id),
  period_start  date NOT NULL,
  period_end    date NOT NULL,
  file_uri      text NOT NULL,
  emailed_at    timestamptz,
  created_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, period_start),
  CHECK (period_end >= period_start)
);

-- =====================================================================
-- reconciliation: our records vs. the chain
-- =====================================================================
CREATE TABLE trading.reconciliation_runs (
  id                uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  started_at        timestamptz NOT NULL DEFAULT now(),
  finished_at       timestamptz,
  accounts_checked  integer NOT NULL DEFAULT 0,
  mismatches        integer NOT NULL DEFAULT 0,
  status            text NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'ok', 'mismatches', 'failed'))
);

CREATE TABLE trading.reconciliation_mismatches (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id         uuid NOT NULL REFERENCES trading.reconciliation_runs(id),
  user_id        uuid NOT NULL,
  account_id     uuid NOT NULL,
  token_id       uuid NOT NULL REFERENCES market.tokens(id),
  ledger_units   app.token_units NOT NULL,
  onchain_units  app.token_units NOT NULL,
  pause_id       uuid REFERENCES app.pauses(id),  -- the auto-trading pause it triggered
  detected_at    timestamptz NOT NULL DEFAULT now(),
  resolved_at    timestamptz,
  resolution     text,
  FOREIGN KEY (account_id, user_id) REFERENCES trading.accounts (id, user_id),
  CHECK (ledger_units <> onchain_units)
);

-- =====================================================================
-- audit: append-only trail of every important action, and every signing
-- request made with our auto-trading key. Exported regularly to S3 under
-- Object Lock.
-- =====================================================================
CREATE TABLE audit.events (
  id           uuid NOT NULL DEFAULT gen_random_uuid(),
  occurred_at  timestamptz NOT NULL DEFAULT now(),
  actor_type   text NOT NULL CHECK (actor_type IN ('user', 'staff', 'service', 'system')),
  actor_id     uuid,                -- the user or staff member
  service      text,                -- e.g. 'trade-router'
  user_id      uuid,                -- the customer the event is about, if any
  action       text NOT NULL,       -- e.g. 'permission.granted', 'limits.updated', 'kill_switch.enabled'
  entity_type  text,
  entity_id    text,
  details      jsonb NOT NULL DEFAULT '{}',
  ip           inet,
  request_id   text,
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);
CREATE TABLE audit.events_default PARTITION OF audit.events DEFAULT;
CREATE INDEX ON audit.events (user_id, occurred_at);
CREATE INDEX ON audit.events (action, occurred_at);

CREATE TABLE audit.signing_log (
  id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  requested_at        timestamptz NOT NULL DEFAULT now(),
  user_id             uuid NOT NULL REFERENCES auth.users(id),
  wallet_id           uuid NOT NULL REFERENCES wallet.wallets(id),
  permission_id       uuid NOT NULL REFERENCES wallet.auto_trade_permissions(id),
  permission_version  integer NOT NULL,
  signal_id           uuid REFERENCES trading.signals(id),
  order_id            uuid NOT NULL REFERENCES trading.orders(id),
  execution_id        uuid REFERENCES trading.executions(id),
  result              text NOT NULL CHECK (result IN ('signed', 'refused_by_policy', 'error')),
  tx_hash             app.tx_hash,
  error               text
);
CREATE INDEX ON audit.signing_log (user_id, requested_at);

-- =====================================================================
-- Triggers: updated_at, and append-only protection
-- =====================================================================
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY[
    'auth.users', 'app.user_settings', 'app.user_limits', 'strategy.risk_levels',
    'strategy.strategies', 'strategy.enrollments', 'strategy.rules',
    'trading.recurring_buys', 'trading.orders', 'ramp.transactions',
    'billing.subscriptions', 'notify.preferences'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER touch_updated_at BEFORE UPDATE ON %s '
      'FOR EACH ROW EXECUTE FUNCTION app.touch_updated_at()', t);
  END LOOP;

  FOREACH t IN ARRAY ARRAY[
    'ledger.entries', 'audit.events', 'audit.signing_log', 'strategy.rule_versions'
  ] LOOP
    EXECUTE format(
      'CREATE TRIGGER append_only BEFORE UPDATE OR DELETE ON %s '
      'FOR EACH ROW EXECUTE FUNCTION app.forbid_change()', t);
    EXECUTE format(
      'CREATE TRIGGER append_only_truncate BEFORE TRUNCATE ON %s '
      'FOR EACH STATEMENT EXECUTE FUNCTION app.forbid_change()', t);
  END LOOP;
END $$;

-- =====================================================================
-- Row-Level Security
-- Every customer table: the App API sees and writes only rows where
-- user_id = app.current_user_id(); workers and admins see all rows.
-- =====================================================================
CREATE FUNCTION app.protect_user_table(t regclass, owner_column text DEFAULT 'user_id') RETURNS void
LANGUAGE plpgsql AS $$
BEGIN
  EXECUTE format('ALTER TABLE %s ENABLE ROW LEVEL SECURITY', t);
  EXECUTE format(
    'CREATE POLICY own_rows ON %s TO osprey_api '
    'USING (%I = app.current_user_id()) WITH CHECK (%I = app.current_user_id())',
    t, owner_column, owner_column);
  EXECUTE format(
    'CREATE POLICY service_rows ON %s TO osprey_worker, osprey_admin USING (true) WITH CHECK (true)', t);
END $$;

DO $$
DECLARE t text;
BEGIN
  PERFORM app.protect_user_table('auth.users', 'id');
  FOREACH t IN ARRAY ARRAY[
    'auth.identities', 'auth.devices', 'auth.sessions',
    'app.user_settings', 'app.user_limits', 'app.pauses', 'app.referral_codes', 'app.referrals',
    'wallet.wallets', 'wallet.auto_trade_permissions', 'wallet.address_book', 'wallet.transfers',
    'trading.accounts', 'trading.recurring_buys', 'trading.orders', 'trading.approvals',
    'trading.executions', 'trading.balances',
    'strategy.enrollments', 'strategy.rules', 'strategy.rule_versions', 'strategy.rule_backtests',
    'ramp.transactions',
    'ledger.entries', 'ledger.tax_lots', 'ledger.tax_exports',
    'billing.subscriptions',
    'notify.notifications', 'notify.preferences', 'notify.statements'
  ] LOOP
    PERFORM app.protect_user_table(t::regclass);
  END LOOP;
END $$;

-- =====================================================================
-- Grants
-- Rule of thumb: the API never deletes, never writes the ledger or audit
-- trail directly, and never sees signals, webhooks, reconciliation or ops.
-- =====================================================================
GRANT USAGE ON SCHEMA app, auth, wallet, market, strategy, trading, ramp, ledger, billing, notify
  TO osprey_api;
GRANT USAGE ON SCHEMA app, auth, wallet, market, strategy, trading, ramp, ledger, billing, notify, ops, audit
  TO osprey_worker, osprey_admin;

-- App API: reference data (read-only)
GRANT SELECT ON
  market.tokens, market.candles, strategy.risk_levels, strategy.risk_level_tokens,
  strategy.strategies, strategy.strategy_versions, strategy.performance,
  strategy.model_account_daily, strategy.halts, billing.plans, billing.current_plans
  TO osprey_api;

-- App API: the user's own rows (RLS applies)
GRANT SELECT, INSERT, UPDATE ON
  auth.users, auth.identities, auth.devices, auth.sessions,
  app.user_settings, app.user_limits, app.pauses, app.referral_codes,
  wallet.wallets, wallet.auto_trade_permissions, wallet.address_book, wallet.transfers,
  trading.recurring_buys, trading.orders, trading.approvals, trading.executions,
  strategy.enrollments, strategy.rules, strategy.rule_backtests,
  ramp.transactions, notify.notifications, notify.preferences
  TO osprey_api;
GRANT SELECT, INSERT ON trading.accounts, strategy.rule_versions, ledger.tax_exports TO osprey_api;
GRANT SELECT ON
  app.referrals, trading.balances, ledger.entries, ledger.tax_lots,
  billing.subscriptions, notify.statements
  TO osprey_api;
GRANT EXECUTE ON FUNCTION auth.user_id_for_privy(text, citext) TO osprey_api;

-- Workers: read and write across users; append-only tables get INSERT only
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA
  app, auth, wallet, market, strategy, trading, ramp, billing, notify, ops
  TO osprey_worker;
GRANT DELETE ON ledger.tax_lots TO osprey_worker;                 -- derived; rebuilt from the ledger
GRANT SELECT, INSERT ON ALL TABLES IN SCHEMA ledger, audit TO osprey_worker;
GRANT UPDATE ON ledger.tax_lots TO osprey_worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ledger, audit TO osprey_worker;

-- Admin dashboard: read everything; act only through these
GRANT SELECT ON ALL TABLES IN SCHEMA
  app, auth, wallet, market, strategy, trading, ramp, ledger, billing, notify, ops, audit
  TO osprey_admin;
GRANT UPDATE ON auth.users, auth.sessions, wallet.auto_trade_permissions, strategy.strategies,
  ops.platform_controls, ops.incidents, trading.reconciliation_mismatches
  TO osprey_admin;
GRANT INSERT, UPDATE ON app.pauses, strategy.halts TO osprey_admin;
GRANT INSERT ON ops.incidents, audit.events TO osprey_admin;

-- =====================================================================
-- Seed data
-- =====================================================================
INSERT INTO strategy.risk_levels (code, name, sort_order, summary, min_cash_pct, max_coin_pct, stop_loss_required) VALUES
  ('steady',   'Steady',   1, 'Smaller swings. Holds BTC, ETH and cash, and rebalances when the mix drifts.', 20, 60, false),
  ('balanced', 'Balanced', 2, 'Normal crypto swings. Buys BTC or ETH after a set drop, with a stop-loss.',  NULL, NULL, true),
  ('bold',     'Bold',     3, 'Big drops for bigger upside. Holds the strongest few tokens, rotating weekly.', NULL, NULL, false);

INSERT INTO ops.platform_controls (key, enabled, reason) VALUES
  ('kill_switch',  false, 'When enabled, the trade router stops every trade immediately'),
  ('auto_trading', true,  'When disabled, no auto-trades run; Approve mode still works'),
  ('new_signups',  true,  'When disabled, new users cannot sign up');

-- Plan names and prices are still open (see business.md); features drive the app.
INSERT INTO billing.plans (code, name, features) VALUES
  ('free',    'Free',    '{"auto_trading": false, "premium_strategies": false, "advanced_rules": false}'),
  ('premium', 'Premium', '{"auto_trading": true,  "premium_strategies": true,  "advanced_rules": false}');

COMMIT;
