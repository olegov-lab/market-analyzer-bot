UPDATE pg_database SET datname='btcbot' WHERE oid=5;
DELETE FROM pg_database WHERE oid=812419;
SELECT oid, datname FROM pg_database;
