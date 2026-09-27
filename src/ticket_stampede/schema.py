"""PostgreSQL schema for safe ticket allocation and idempotent purchases."""

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    String,
    Table,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID

metadata = MetaData()

sales = Table(
    "sales",
    metadata,
    Column("sale_id", UUID(as_uuid=True), primary_key=True),
    Column("capacity", Integer, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
)

tickets = Table(
    "tickets",
    metadata,
    Column("sale_id", UUID(as_uuid=True), ForeignKey("sales.sale_id"), nullable=False),
    Column("ticket_number", Integer, nullable=False),
    Column("state", String(16), nullable=False, server_default="available"),
    CheckConstraint("state IN ('available', 'issued')", name="ticket_state_is_valid"),
    # Explicit inventory means capacity is represented by real ticket rows.
    # It also makes a duplicate ticket number structurally impossible.
    PrimaryKeyConstraint("sale_id", "ticket_number"),
)

purchase_requests = Table(
    "purchase_requests",
    metadata,
    Column("sale_id", UUID(as_uuid=True), nullable=False),
    Column("request_id", String(128), nullable=False),
    Column("user_id", String(128), nullable=False),
    Column("outcome", String(16), nullable=False),
    Column("ticket_number", Integer, nullable=True),
    Column("created_at", DateTime(timezone=True), server_default=func.now()),
    ForeignKeyConstraint(["sale_id"], ["sales.sale_id"]),
    ForeignKeyConstraint(
        ["sale_id", "ticket_number"], ["tickets.sale_id", "tickets.ticket_number"]
    ),
    # The durable request record is the idempotency boundary.
    PrimaryKeyConstraint("sale_id", "request_id"),
    # PostgreSQL permits multiple NULLs here, so many sold-out rows remain valid,
    # while an issued ticket number can only appear once per sale.
    UniqueConstraint("sale_id", "ticket_number", name="one_purchase_per_ticket"),
    CheckConstraint(
        "(outcome = 'issued' AND ticket_number IS NOT NULL) "
        "OR (outcome IN ('processing', 'sold_out') AND ticket_number IS NULL)",
        name="purchase_outcome_matches_ticket",
    ),
)
