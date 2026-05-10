"""initial_schema

Revision ID: ff915dee903b
Revises:
Create Date: 2026-05-10 10:20:18.077922

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'ff915dee903b'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE")

    op.create_table(
        "prices",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    )
    op.execute(
        "SELECT create_hypertable('prices', 'time', "
        "chunk_time_interval => INTERVAL '1 day')"
    )

    op.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS candles_1m
        WITH (timescaledb.continuous) AS
        SELECT
            time_bucket('1 minute', time) AS bucket,
            symbol,
            FIRST(price, time) AS open,
            MAX(price) AS high,
            MIN(price) AS low,
            LAST(price, time) AS close,
            SUM(volume) AS volume
        FROM prices
        GROUP BY bucket, symbol
        WITH NO DATA
    """)
    op.execute(
        "SELECT add_continuous_aggregate_policy('candles_1m', "
        "start_offset => INTERVAL '1 day', "
        "end_offset => INTERVAL '1 hour', "
        "schedule_interval => INTERVAL '1 minute')"
    )
    op.execute(
        "SELECT add_retention_policy('prices', INTERVAL '7 days')"
    )

    op.create_table(
        "users",
        sa.Column("user_id", sa.BigInteger(), primary_key=True),
        sa.Column("username", sa.Text(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="TRUE"),
        sa.Column("timezone", sa.Text(), server_default="UTC"),
    )

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("user_id", sa.BigInteger(),
                  sa.ForeignKey("users.user_id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("symbol", sa.Text(), nullable=False),
        sa.Column("interval", sa.Text(), server_default="15m"),
        sa.Column("alert_types", postgresql.ARRAY(sa.Text()),
                  server_default="'{}'"),
    )

    op.create_table(
        "predictions",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("horizon", sa.Text(), nullable=False),
        sa.Column("price_min", sa.Float(), nullable=False),
        sa.Column("price_max", sa.Float(), nullable=False),
        sa.Column("direction", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("meta", postgresql.JSONB(), server_default="'{}'"),
    )

    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), primary_key=True,
                  autoincrement=True),
        sa.Column("user_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_type", sa.Text(), nullable=False),
        sa.Column("price", sa.Float(), nullable=True),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("sent", sa.Boolean(), server_default="FALSE"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True),
                  server_default=sa.func.now()),
    )

    op.create_table(
        "onchain_metrics",
        sa.Column("time", sa.TIMESTAMP(timezone=True), nullable=False),
        sa.Column("metric_name", sa.Text(), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("onchain_metrics")
    op.drop_table("alerts")
    op.drop_table("predictions")
    op.drop_table("subscriptions")
    op.drop_table("users")
    op.execute("DROP MATERIALIZED VIEW IF EXISTS candles_1m CASCADE")
    op.execute("DROP TABLE IF EXISTS prices CASCADE")
    op.execute("DROP EXTENSION IF EXISTS timescaledb CASCADE")
