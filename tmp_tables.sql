SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('public','btcbot') ORDER BY 1,2 LIMIT 30;
SELECT relname, relkind FROM pg_class WHERE relkind='r' AND relnamespace::regnamespace::text IN ('public','btcbot') ORDER BY 1;
