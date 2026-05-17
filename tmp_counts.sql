SELECT 'users', count(*) FROM users
UNION ALL SELECT 'user_subscriptions', count(*) FROM user_subscriptions
UNION ALL SELECT 'prices', count(*) FROM prices
UNION ALL SELECT 'positions', count(*) FROM positions
UNION ALL SELECT 'trades', count(*) FROM trades
UNION ALL SELECT 'game_users', count(*) FROM game_users
UNION ALL SELECT 'alerts', count(*) FROM alerts
UNION ALL SELECT 'onchain_metrics', count(*) FROM onchain_metrics;
