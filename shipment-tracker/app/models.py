from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


TS = DateTime(timezone=True)


class User(Base):
    """A login. Role 'party' sees shipments whose PartyName is in its party_names;
    role 'admin' (Balaji Transports staff) sees everything and manages the user master."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    company: Mapped[str] = mapped_column(String(255), default="")
    email: Mapped[str] = mapped_column(String(255), default="")
    phone: Mapped[str] = mapped_column(String(32), default="")
    role: Mapped[str] = mapped_column(String(16), default="party")
    password_hash: Mapped[str] = mapped_column(String(128))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    token_version: Mapped[int] = mapped_column(Integer, default=1)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    whatsapp_alerts: Mapped[bool] = mapped_column(Boolean, default=True)
    password_changed_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    created_at: Mapped[datetime] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS)

    party_names: Mapped[list["UserPartyName"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", lazy="selectin", order_by="UserPartyName.party_name")


class UserPartyName(Base):
    """One upstream PartyName a user may track. Matching uses party_key (case/punctuation-insensitive)."""
    __tablename__ = "user_party_names"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    party_name: Mapped[str] = mapped_column(String(255))
    party_key: Mapped[str] = mapped_column(String(255), index=True)

    user: Mapped[User] = relationship(back_populates="party_names")
    __table_args__ = (UniqueConstraint("user_id", "party_key", name="uq_user_party_key"),)


class Shipment(Base):
    __tablename__ = "shipments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)  # upstream ShipmentID
    party_name_raw: Mapped[str] = mapped_column(String(255), default="")
    party_key: Mapped[str] = mapped_column(String(255), default="", index=True)
    vehicle_id: Mapped[int] = mapped_column(Integer, index=True)
    vehicle_no: Mapped[str] = mapped_column(String(32), default="")
    driver_name: Mapped[str] = mapped_column(String(128), default="")
    driver_phones: Mapped[str] = mapped_column(String(64), default="")
    product: Mapped[str] = mapped_column(String(128), default="")
    net_weight: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    shipment_date: Mapped[str] = mapped_column(String(10), default="")
    origin: Mapped[str] = mapped_column(String(64), default="")
    destination: Mapped[str] = mapped_column(String(64), default="")
    destination_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    unload_site: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(24), index=True)
    status_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    delivered_inferred: Mapped[bool] = mapped_column(Boolean, default=False)
    superseded_by: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    milestones: Mapped[dict] = mapped_column(JSON, default=dict)
    first_seen_at: Mapped[datetime] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS)

    __table_args__ = (Index("ix_shipments_key_status", "party_key", "status"),)


class VehiclePosition(Base):
    __tablename__ = "vehicle_positions"
    vehicle_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    heading: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    fix_at: Mapped[datetime] = mapped_column(TS)
    updated_at: Mapped[datetime] = mapped_column(TS)


class TrackPoint(Base):
    __tablename__ = "track_points"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shipment_id: Mapped[int] = mapped_column(Integer, index=True)
    lat: Mapped[float] = mapped_column(Float)
    lng: Mapped[float] = mapped_column(Float)
    at: Mapped[datetime] = mapped_column(TS, index=True)


class Notification(Base):
    """Per-user, so read state is per user and adding/removing party names never leaks history."""
    __tablename__ = "notifications"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    shipment_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(24))
    title: Mapped[str] = mapped_column(String(160))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS)
    read_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)

    __table_args__ = (Index("ix_notifications_user_id", "user_id", "id"),)


class AuditLog(Base):
    """Who changed what in the user master."""
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor: Mapped[str] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(48))
    target: Mapped[str] = mapped_column(String(128))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    at: Mapped[datetime] = mapped_column(TS, index=True)


class SyncState(Base):
    __tablename__ = "sync_state"
    key: Mapped[str] = mapped_column(String(32), primary_key=True)
    ok_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    error_at: Mapped[Optional[datetime]] = mapped_column(TS, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")


class AppSetting(Base):
    """Small key/value store for admin-editable settings (e.g. the customer-care contact)."""
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(TS)
    updated_by: Mapped[str] = mapped_column(String(64), default="")


class LoginAttempt(Base):
    """Failed login attempts, persisted so throttle state survives restarts."""
    __tablename__ = "login_attempts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(128), index=True)
    at: Mapped[datetime] = mapped_column(TS)
