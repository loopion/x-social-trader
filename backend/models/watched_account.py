from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.base import Base, TimestampMixin, UpdateTimestampMixin


class WatchedAccount(Base, TimestampMixin, UpdateTimestampMixin):
    __tablename__ = "watched_accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    # x_user_id is populated once we discover the account on first tweet.
    x_user_id: Mapped[str | None] = mapped_column(String(32), index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
