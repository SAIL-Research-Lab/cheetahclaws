"""Accounts, credits, usage and payments (SQLAlchemy; SQLite by default).

Money is stored as integer micro-dollars (1 USD = 1_000_000) so repeated
small charges never accumulate float rounding error.
"""
from __future__ import annotations

import time
from typing import Optional

from sqlalchemy import (Integer, String, Text, Float, create_engine, event,
                        select, update)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

MICRO = 1_000_000


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    created_at: Mapped[float] = mapped_column(Float, default=time.time)
    balance_micro: Mapped[int] = mapped_column(Integer, default=0)
    # "platform" = our metered models; "byok" = the user's own provider key.
    model_mode: Mapped[str] = mapped_column(String(16), default="platform")
    platform_model: Mapped[str] = mapped_column(String(128), default="")
    byok_provider: Mapped[str] = mapped_column(String(32), default="")
    byok_model: Mapped[str] = mapped_column(String(200), default="")
    byok_base_url: Mapped[str] = mapped_column(String(500), default="")
    byok_key_enc: Mapped[str] = mapped_column(Text, default="")
    # Bumped whenever settings that shape the sandbox change; the sandbox
    # manager recreates the container when its label no longer matches.
    settings_rev: Mapped[int] = mapped_column(Integer, default=1)


class Usage(Base):
    __tablename__ = "usage"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(Integer, index=True)
    ts: Mapped[float] = mapped_column(Float, default=time.time)
    model: Mapped[str] = mapped_column(String(128))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_micro: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Kept (with user_id NULL) after account deletion, for bookkeeping.
    user_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    provider: Mapped[str] = mapped_column(String(16), default="stripe")
    external_id: Mapped[str] = mapped_column(String(200), unique=True)
    amount_micro: Mapped[int] = mapped_column(Integer)
    ts: Mapped[float] = mapped_column(Float, default=time.time)


class Database:
    def __init__(self, url: str):
        kw = {}
        if url.startswith("sqlite"):
            kw["connect_args"] = {"check_same_thread": False, "timeout": 30}
        self.engine = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _pragmas(conn, _rec):  # noqa: ANN001
                cur = conn.cursor()
                cur.execute("PRAGMA journal_mode=WAL")
                cur.execute("PRAGMA busy_timeout=30000")
                cur.close()
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self.Session()

    # ── users ────────────────────────────────────────────────────────────
    def get_user(self, uid: int) -> Optional[User]:
        with self.session() as s:
            return s.get(User, uid)

    def get_user_by_email(self, email: str) -> Optional[User]:
        with self.session() as s:
            return s.scalar(select(User).where(User.email == email))

    def create_user(self, email: str, password_hash: str, credit_micro: int,
                    platform_model: str) -> User:
        with self.session() as s:
            u = User(email=email, password_hash=password_hash,
                     balance_micro=credit_micro, platform_model=platform_model)
            s.add(u)
            s.commit()
            return u

    def update_user(self, uid: int, bump_rev: bool = False, **fields) -> Optional[User]:
        with self.session() as s:
            u = s.get(User, uid)
            if not u:
                return None
            for k, v in fields.items():
                setattr(u, k, v)
            if bump_rev:
                u.settings_rev = (u.settings_rev or 1) + 1
            s.commit()
            return u

    def delete_user(self, uid: int) -> None:
        with self.session() as s:
            s.query(Usage).filter(Usage.user_id == uid).delete()
            s.query(Payment).filter(Payment.user_id == uid).update({Payment.user_id: None})
            u = s.get(User, uid)
            if u:
                s.delete(u)
            s.commit()

    # ── credits ──────────────────────────────────────────────────────────
    def charge(self, uid: int, model: str, in_tok: int, out_tok: int,
               cost_micro: int) -> int:
        """Record usage and deduct atomically. Returns the new balance."""
        with self.session() as s:
            s.execute(update(User).where(User.id == uid)
                      .values(balance_micro=User.balance_micro - cost_micro))
            s.add(Usage(user_id=uid, model=model, input_tokens=in_tok,
                        output_tokens=out_tok, cost_micro=cost_micro))
            s.commit()
            return s.scalar(select(User.balance_micro).where(User.id == uid)) or 0

    def credit(self, uid: int, amount_micro: int, provider: str,
               external_id: str) -> bool:
        """Add credit once per external payment id. False if already applied."""
        with self.session() as s:
            if s.scalar(select(Payment).where(Payment.external_id == external_id)):
                return False
            s.add(Payment(user_id=uid, provider=provider, external_id=external_id,
                          amount_micro=amount_micro))
            s.execute(update(User).where(User.id == uid)
                      .values(balance_micro=User.balance_micro + amount_micro))
            s.commit()
            return True

    def recent_usage(self, uid: int, limit: int = 20) -> list[Usage]:
        with self.session() as s:
            return list(s.scalars(select(Usage).where(Usage.user_id == uid)
                                  .order_by(Usage.id.desc()).limit(limit)))
