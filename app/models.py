from __future__ import annotations
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, JSON, String, Text, UniqueConstraint, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

def uid(): return uuid.uuid4().hex

def now(): return datetime.utcnow()

class Base(DeclarativeBase): pass

class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class LoginSession(Base):
    __tablename__ = 'sessions'
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    csrf: Mapped[str] = mapped_column(String(64))
    expires: Mapped[datetime] = mapped_column(DateTime)

class SMTPProfile(Base):
    __tablename__ = 'smtp_profiles'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    security: Mapped[str] = mapped_column(String(12))
    username: Mapped[str] = mapped_column(String(254))
    sender_name: Mapped[str] = mapped_column(String(100))
    sender_email: Mapped[str] = mapped_column(String(254))
    reply_to: Mapped[str] = mapped_column(String(254), default='')
    credential_ref: Mapped[str] = mapped_column(String(64), unique=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

class Classroom(Base):
    __tablename__ = 'classes'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))

class Student(Base):
    __tablename__ = 'students'
    __table_args__ = (UniqueConstraint('class_id', 'email'),)
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    class_id: Mapped[str] = mapped_column(ForeignKey('classes.id', ondelete='CASCADE'))
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))

class MailTemplate(Base):
    __tablename__ = 'templates'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(100))
    subject: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    delta: Mapped[dict] = mapped_column(JSON)
    builtin: Mapped[bool] = mapped_column(Boolean, default=False)

class Notice(Base):
    __tablename__ = 'notices'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class SendJob(Base):
    __tablename__ = 'send_jobs'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    idempotency_key: Mapped[str] = mapped_column(String(100), unique=True)
    profile_id: Mapped[str] = mapped_column(String(32), index=True)
    smtp_snapshot: Mapped[dict] = mapped_column(JSON)
    notice_snapshot: Mapped[dict] = mapped_column(JSON)
    subject: Mapped[str] = mapped_column(String(300))
    interval: Mapped[int] = mapped_column(Integer, default=3)
    status: Mapped[str] = mapped_column(String(20), default='queued', index=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str] = mapped_column(Text, default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Delivery(Base):
    __tablename__ = 'deliveries'
    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=uid)
    job_id: Mapped[str] = mapped_column(ForeignKey('send_jobs.id', ondelete='CASCADE'), index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    student_id: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(254))
    class_name: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(20), default='pending')
    detail: Mapped[str] = mapped_column(String(300), default='')
    message_id: Mapped[str] = mapped_column(String(255))


def database(path):
    engine = create_engine('sqlite:///' + str(path), connect_args={'check_same_thread': False, 'timeout': 15})
    @event.listens_for(engine, 'connect')
    def pragmas(conn, record):
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA journal_mode=WAL')
        conn.execute('PRAGMA busy_timeout=15000')
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine, expire_on_commit=False)
