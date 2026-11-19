-- =====================================================================
-- Spot checks for schema.sql. Run ONLY against a scratch database:
--
--   createdb osprey_scratch
--   psql -d osprey_scratch -v ON_ERROR_STOP=1 -f schema.sql
--   psql -d osprey_scratch -f schema_checks.sql
--
-- Prints PASS/FAIL per rule, then a total. Creates throwaway test data.
-- These are spot checks; the backend's real test suite (database.md,
-- "Required tests") goes further.
-- =====================================================================
\set ON_ERROR_STOP 1
SET client_min_messages = warning;

-- ---------- test data (as the owner) ----------
SELECT auth.user_id_for_privy('did:privy:a', 'a@example.com') AS a \gset
SELECT auth.user_id_for_privy('did:privy:b', 'b@example.com') AS b \gset
INSERT INTO market.tokens (chain_id, symbol, display_symbol, name, contract_address, decimals, is_stablecoin)
VALUES (84532, 'USDC', 'USD', 'USD Coin (test)', '0x' || repeat('1', 40), 6, true) RETURNING id AS usdc \gset
INSERT INTO market.tokens (chain_id, symbol, display_symbol, name, contract_address, decimals)
VALUES (84532, 'cbBTC', 'BTC', 'Coinbase Wrapped BTC (test)', '0x' || repeat('2', 40), 8) RETURNING id AS btc \gset
INSERT INTO wallet.wallets (user_id, chain_id, address, kind, is_primary)
VALUES (:'a', 84532, '0x' || repeat('a', 40), 'smart', true) RETURNING id AS wa \gset
INSERT INTO wallet.wallets (user_id, chain_id, address, kind, is_primary)
VALUES (:'b', 84532, '0x' || repeat('b', 40), 'smart', true) RETURNING id AS wb \gset
INSERT INTO trading.accounts (user_id, kind, wallet_id) VALUES (:'a', 'live', :'wa') RETURNING id AS acct_a \gset
INSERT INTO trading.accounts (user_id, kind, wallet_id) VALUES (:'b', 'live', :'wb') RETURNING id AS acct_b \gset
INSERT INTO strategy.strategies (slug, name, risk_level, summary, status)
VALUES ('dip-buy-balanced', 'Dip buy', 'balanced', 'Buys dips', 'live') RETURNING id AS strat \gset
INSERT INTO strategy.strategy_versions (strategy_id, version, config, code_commit, approved_at, is_current)
VALUES (:'strat', 1, '{}', 'abc123', now(), true) RETURNING id AS sv \gset
INSERT INTO strategy.enrollments (user_id, account_id, strategy_id, mode, allocation_usd)
VALUES (:'a', :'acct_a', :'strat', 'auto', 500) RETURNING id AS enr \gset
INSERT INTO trading.signals (external_id, source, strategy_version_id, token_id, side, target_weight, reason,
                             price_at_decision, created_at, expires_at)
VALUES ('sig-1', 'strategy', :'sv', :'btc', 'buy', 0.25, 'BTC dropped 6% today', 60000, now(), now() + interval '5 min')
RETURNING id AS sig \gset
INSERT INTO strategy.rules (user_id, account_id, name, mode) VALUES (:'a', :'acct_a', 'dip', 'auto') RETURNING id AS rule \gset
-- 120 one-minute bars, 10:00-11:59 UTC: open = 100 + i, close = open + 0.5, high = close + 1, low = open - 1
INSERT INTO market.candles (token_id, bar_size, open_time, open, high, low, close, volume, source)
SELECT :'btc', '1m', timestamptz '2026-11-19 10:00:00+00' + i * interval '1 minute',
       100 + i, 101.5 + i, 99 + i, 100.5 + i, 1, 'coinbase'
FROM generate_series(0, 119) AS i;
INSERT INTO trading.account_value_daily (account_id, day, user_id, value_usd, cash_usd, net_deposits_usd)
VALUES (:'acct_a', '2026-11-18', :'a', 1000, 400, 900), (:'acct_b', '2026-11-18', :'b', 50, 50, 50);

CREATE TEMP TABLE results (check_name text, ok boolean);
GRANT ALL ON results TO PUBLIC;
CREATE FUNCTION pg_temp.expect_error(name text, stmt text) RETURNS void LANGUAGE plpgsql AS $f$
BEGIN
  BEGIN
    EXECUTE stmt;
    INSERT INTO results VALUES (name, false);
  EXCEPTION WHEN OTHERS THEN
    INSERT INTO results VALUES (name, true);
  END;
END $f$;

-- ---------- charts ----------
INSERT INTO results SELECT 'chart 1H: 60 one-minute bars', count(*) = 60
  FROM market.chart(:'btc', '1H', '2026-11-19 12:00:00+00');
INSERT INTO results SELECT 'chart 1D: 1-minute bars grouped into 24 five-minute bars', count(*) = 24
  FROM market.chart(:'btc', '1d', '2026-11-19 12:00:00+00');
INSERT INTO results SELECT 'chart bucket OHLC: first open, highest high, lowest low, last close, summed volume',
  open = 100 AND high = 105.5 AND low = 99 AND close = 104.5 AND volume = 5
  FROM market.chart(:'btc', '1D', '2026-11-19 12:00:00+00') ORDER BY bucket_start LIMIT 1;
INSERT INTO results SELECT 'chart range ends at "now" (no future bars)', max(bucket_start) < timestamptz '2026-11-19 11:30:00+00'
  FROM market.chart(:'btc', '1H', '2026-11-19 11:30:00+00');
INSERT INTO results SELECT 'weekly buckets start on Mondays (UTC)', extract(isodow FROM bucket_start AT TIME ZONE 'UTC') = 1
  FROM market.chart_bars(:'btc', '1m', interval '7 days', '2026-11-01', '2026-12-01');
INSERT INTO results SELECT '1-minute bars land in the 1m partition', bool_and(tableoid = 'market.candles_1m_default'::regclass)
  FROM market.candles WHERE bar_size = '1m';
SELECT pg_temp.expect_error('unknown chart range rejected',
  format('SELECT * FROM market.chart(%L, %L)', :'btc', '2Y'));
SELECT pg_temp.expect_error('bar not on a minute boundary rejected',
  format($$INSERT INTO market.candles (token_id, bar_size, open_time, open, high, low, close, source)
           VALUES (%L, '1m', '2026-11-19 09:00:30+00', 1, 1, 1, 1, 'coinbase')$$, :'btc'));
SELECT pg_temp.expect_error('bar with high below close rejected',
  format($$INSERT INTO market.candles (token_id, bar_size, open_time, open, high, low, close, source)
           VALUES (%L, '1h', '2026-11-19 09:00:00+00', 10, 9, 8, 10, 'rollup')$$, :'btc'));

-- ---------- duplicates and safety rules (as a worker) ----------
SET ROLE osprey_worker;
SELECT pg_temp.expect_error('duplicate signal ID rejected',
  format($$INSERT INTO trading.signals (external_id, source, strategy_version_id, token_id, side, target_weight, reason,
           price_at_decision, created_at, expires_at)
           VALUES ('sig-1', 'strategy', %L, %L, 'buy', 0.25, 'x', 1, now(), now() + interval '1 min')$$, :'sv', :'btc'));
INSERT INTO trading.orders (user_id, account_id, origin, mode, signal_id, enrollment_id, sell_token_id, buy_token_id,
                            sell_amount_units, notional_usd, slippage_bps, reason, idempotency_key)
VALUES (:'a', :'acct_a', 'strategy', 'auto', :'sig', :'enr', :'usdc', :'btc', 100000000, 100, 100,
        'BTC dropped 6% today', 'sig-1:' || :'acct_a') RETURNING id AS ord \gset
SELECT pg_temp.expect_error('second order for the same signal and account rejected',
  format($$INSERT INTO trading.orders (user_id, account_id, origin, mode, signal_id, enrollment_id, sell_token_id,
           buy_token_id, sell_amount_units, notional_usd, slippage_bps, reason, idempotency_key)
           VALUES (%L, %L, 'strategy', 'auto', %L, %L, %L, %L, 1, 1, 100, 'x', 'other-key')$$,
         :'a', :'acct_a', :'sig', :'enr', :'usdc', :'btc'));
SELECT pg_temp.expect_error('order on another user''s account rejected',
  format($$INSERT INTO trading.orders (user_id, account_id, origin, mode, sell_token_id, buy_token_id,
           sell_amount_units, notional_usd, slippage_bps, reason, idempotency_key)
           VALUES (%L, %L, 'manual', 'manual', %L, %L, 1, 1, 100, 'x', 'k3')$$, :'a', :'acct_b', :'usdc', :'btc'));
INSERT INTO wallet.auto_trade_permissions (user_id, wallet_id, version, status, policy, allowed_token_ids,
                                           max_per_trade_usd, max_per_day_usd, granted_at, expires_at)
VALUES (:'a', :'wa', 1, 'active', '{}', ARRAY[:'btc']::uuid[], 100, 300, now(), now() + interval '90 days')
RETURNING id AS perm \gset
SELECT pg_temp.expect_error('second active permission on one wallet rejected',
  format($$INSERT INTO wallet.auto_trade_permissions (user_id, wallet_id, version, status, policy, allowed_token_ids,
           max_per_trade_usd, max_per_day_usd, granted_at, expires_at)
           VALUES (%L, %L, 2, 'active', '{}', '{}', 100, 300, now(), now() + interval '30 days')$$, :'a', :'wa'));
SELECT pg_temp.expect_error('permission longer than 90 days rejected',
  format($$INSERT INTO wallet.auto_trade_permissions (user_id, wallet_id, version, status, policy, allowed_token_ids,
           max_per_trade_usd, max_per_day_usd, granted_at, expires_at)
           VALUES (%L, %L, 3, 'pending', '{}', '{}', 100, 300, now(), now() + interval '91 days')$$, :'a', :'wa'));
INSERT INTO trading.orders (user_id, account_id, origin, mode, sell_token_id, buy_token_id, sell_amount_units,
                            notional_usd, slippage_bps, reason, idempotency_key)
VALUES (:'b', :'acct_b', 'manual', 'manual', :'usdc', :'btc', 1, 1, 100, 'manual buy', 'manual-b-1')
RETURNING id AS ord_b \gset
SELECT pg_temp.expect_error('execution using another user''s permission rejected',
  format($$INSERT INTO trading.executions (order_id, user_id, kind, signed_by, permission_id, chain_id, sell_amount_units)
           VALUES (%L, %L, 'onchain', 'permission', %L, 84532, 1)$$, :'ord_b', :'b', :'perm'));
INSERT INTO trading.executions (order_id, user_id, kind, signed_by, permission_id, chain_id, sell_amount_units,
                                min_buy_amount_units)
VALUES (:'ord', :'a', 'onchain', 'permission', :'perm', 84532, 100000000, 150000) RETURNING id AS ex \gset
SELECT pg_temp.expect_error('confirmed swap below its price protection rejected',
  format($$UPDATE trading.executions SET status = 'confirmed', buy_amount_units = 100 WHERE id = %L$$, :'ex'));
SELECT pg_temp.expect_error('outgoing transfer without Face ID rejected',
  format($$INSERT INTO wallet.transfers (user_id, account_id, direction, purpose, token_id, amount_units,
           counterparty, status) VALUES (%L, %L, 'out', 'send', %L, 5, %L, 'submitted')$$,
         :'a', :'acct_a', :'usdc', '0x' || repeat('c', 40)));
SELECT pg_temp.expect_error('rule version without a stop-loss rejected',
  format($$INSERT INTO strategy.rule_versions (rule_id, version, user_id, token_id, definition, stop_loss_pct)
           VALUES (%L, 1, %L, %L, '{}', NULL)$$, :'rule', :'a', :'btc'));
UPDATE trading.executions SET status = 'confirmed', buy_amount_units = 160000, confirmed_at = now() WHERE id = :'ex';
INSERT INTO ledger.entries (user_id, account_id, token_id, amount_units, kind, execution_id, occurred_at) VALUES
  (:'a', :'acct_a', :'usdc', -100000000, 'swap_out', :'ex', now()),
  (:'a', :'acct_a', :'btc', 160000, 'swap_in', :'ex', now());
SELECT pg_temp.expect_error('ledger entry with the wrong sign rejected',
  format($$INSERT INTO ledger.entries (user_id, account_id, token_id, amount_units, kind, execution_id, occurred_at)
           VALUES (%L, %L, %L, 5, 'swap_out', %L, now())$$, :'a', :'acct_a', :'usdc', :'ex'));
SELECT pg_temp.expect_error('ledger update blocked', 'UPDATE ledger.entries SET note = ''x''');
SELECT pg_temp.expect_error('ledger delete blocked', 'DELETE FROM ledger.entries');
RESET ROLE;
SELECT pg_temp.expect_error('ledger truncate blocked, even for the owner', 'TRUNCATE ledger.entries');
INSERT INTO audit.events (actor_type, action) VALUES ('system', 'test');
SELECT pg_temp.expect_error('audit update blocked (partitioned table)', 'UPDATE audit.events SET action = ''x''');

-- ---------- Row-Level Security and role limits (as the App API) ----------
SET ROLE osprey_api;
INSERT INTO results SELECT 'API with no user set sees no wallets', count(*) = 0 FROM wallet.wallets;
SELECT set_config('app.user_id', :'a', false) \gset
INSERT INTO results SELECT 'user A sees only their own wallet', count(*) = 1 AND bool_and(user_id = :'a') FROM wallet.wallets;
INSERT INTO results SELECT 'user A sees only their own user row', count(*) = 1 FROM auth.users;
INSERT INTO results SELECT 'user A sees their own ledger entries', count(*) = 2 FROM ledger.entries;
INSERT INTO results SELECT 'user A sees only their own portfolio chart', count(*) = 1 AND bool_and(value_usd = 1000)
  FROM trading.account_value_daily;
WITH u AS (UPDATE wallet.wallets SET is_primary = false WHERE user_id = :'b' RETURNING 1)
INSERT INTO results SELECT 'user A cannot update user B''s wallet', count(*) = 0 FROM u;
SELECT pg_temp.expect_error('user A cannot insert a row as user B',
  format($$INSERT INTO wallet.address_book (user_id, chain_id, address, label) VALUES (%L, 84532, %L, 'x')$$,
         :'b', '0x' || repeat('d', 40)));
SELECT pg_temp.expect_error('API cannot delete', 'DELETE FROM wallet.address_book');
SELECT pg_temp.expect_error('API cannot write the ledger',
  format($$INSERT INTO ledger.entries (user_id, account_id, token_id, amount_units, kind, occurred_at)
           VALUES (%L, %L, %L, 1, 'demo_credit', now())$$, :'a', :'acct_a', :'usdc'));
SELECT pg_temp.expect_error('API cannot write chart history',
  format($$INSERT INTO market.candles (token_id, bar_size, open_time, open, high, low, close, source)
           VALUES (%L, '1d', '2026-11-18', 1, 1, 1, 1, 'x')$$, :'btc'));
SELECT pg_temp.expect_error('API cannot read signals', 'SELECT 1 FROM trading.signals');
SELECT pg_temp.expect_error('API cannot read the audit trail', 'SELECT 1 FROM audit.events');
SELECT pg_temp.expect_error('API cannot read webhooks', 'SELECT 1 FROM ramp.webhook_events');
INSERT INTO results SELECT 'API can load a chart', count(*) = 60 FROM market.chart(:'btc', '1H', '2026-11-19 12:00:00+00');
INSERT INTO results SELECT 'sign-in helper returns the same user every time', auth.user_id_for_privy('did:privy:a') = :'a';
INSERT INTO results SELECT 'API reads reference data', count(*) = 3 FROM strategy.risk_levels;
RESET ROLE;

-- ---------- results ----------
SELECT CASE WHEN ok THEN 'PASS' ELSE 'FAIL' END AS result, check_name FROM results ORDER BY ok, check_name;
SELECT count(*) FILTER (WHERE ok) AS passed, count(*) FILTER (WHERE NOT ok) AS failed FROM results;
