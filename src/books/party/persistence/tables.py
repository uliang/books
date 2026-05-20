"""Party ORM tables (ADR-0013). Private to the Party context."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from books.platform.db import Base


class _Party(Base):
    __tablename__ = "party"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
