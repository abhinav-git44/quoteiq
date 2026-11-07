"""Initial schema.

The baseline is created from the SQLAlchemy metadata (single source of truth for this first
revision). Subsequent changes should be generated with `alembic revision --autogenerate`.

Revision ID: 0001_initial
Revises:
Create Date: 2026-11-05
"""
from alembic import op

from app.db.models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    Base.metadata.create_all(bind=op.get_bind())


def downgrade():
    Base.metadata.drop_all(bind=op.get_bind())
