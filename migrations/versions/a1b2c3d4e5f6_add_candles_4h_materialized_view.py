"""add_candles_4h_materialized_view

Revision ID: a1b2c3d4e5f6
Revises: ff915dee903b
Create Date: 2026-05-10 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'ff915dee903b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS candles_4h
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('4 hours', bucket) AS bucket,
            symbol,
            FIRST(open, bucket) AS open,
            MAX(high) AS high,
            MIN(low) AS low,
            LAST(close, bucket) AS close,
            SUM(volume) AS volume
        FROM candles_1m
        GROUP BY time_bucket('4 hours', bucket), symbol
        WITH NO DATA
    """)
    op.execute(
        "SELECT add_continuous_aggregate_policy('candles_4h', "
        "start_offset => INTERVAL '7 days', "
        "end_offset => INTERVAL '1 hour', "
        "schedule_interval => INTERVAL '1 hour')"
    )
    op.execute("CALL refresh_continuous_aggregate('candles_4h', NULL, NULL)")


def downgrade() -> None:
    op.execute("DROP MATERIALIZED VIEW IF EXISTS candles_4h CASCADE")
