SELECT default_version, installed_version FROM pg_available_extensions WHERE name='timescaledb';
SELECT * FROM _timescaledb_catalog.hypertable;
SELECT chunk_schema, chunk_name, hypertable_id FROM _timescaledb_catalog.chunk LIMIT 10;
SELECT count(*) as total_relations FROM pg_class;
SELECT relname, relkind FROM pg_class WHERE relkind='r' AND relnamespace::regnamespace::text NOT LIKE 'pg_%' LIMIT 20;
