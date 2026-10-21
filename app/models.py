import enum
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    Integer,
    String,
    Text,
    Boolean,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from app.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class RoleEnum(str, enum.Enum):
    ADMIN = "ADMIN"
    GROUP_LEADER = "GROUP_LEADER"
    VIEWER = "VIEWER"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=False)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default=RoleEnum.VIEWER.value, nullable=False)
    assigned_group = Column(String(50), nullable=True)  # np. "1", "2", "Lab 1A" dla starostów grup
    avatar_url = Column(Text, nullable=True)  # Zdjęcie profilowe użytkownika (URL lub Data URI)
    is_active = Column(Boolean, default=True, nullable=False)
    must_change_password = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class Student(Base):
    __tablename__ = "students"

    id = Column(Integer, primary_key=True, index=True)
    imie = Column(String(120), nullable=False, index=True)
    nazwisko = Column(String(120), nullable=False, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    grupa = Column(String(60), nullable=False, index=True)
    komentarz = Column(Text, default="", nullable=False)
    utworzono_data = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    code = Column(String(60), nullable=False, index=True)  # np. RAU2-SI-2026
    name = Column(String(255), nullable=False)
    lecturer = Column(String(255), default="", nullable=False)
    rau2_url = Column(String(500), default="", nullable=False)  # https://platforma.polsl.pl/rau2/course/view.php?id=...
    usos_url = Column(String(500), default="", nullable=False)
    passing_rules = Column(Text, default="", nullable=False)
    assigned_groups = Column(String(255), default="Wszystkie", nullable=False)
    ects = Column(Integer, default=3, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class CalendarFeed(Base):
    __tablename__ = "calendar_feeds"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(150), nullable=False)  # np. "USOSweb - Plan RAU2", "Moodle RAU2 Deadlines"
    source_type = Column(String(50), default="USOS", nullable=False)  # USOS | RAU2_MOODLE | CUSTOM
    ics_url = Column(String(1000), nullable=False)
    target_group = Column(String(60), default="Wszystkie", nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)

    events = relationship("CalendarEvent", back_populates="feed", cascade="all, delete-orphan")


class CalendarEvent(Base):
    __tablename__ = "calendar_events"

    id = Column(Integer, primary_key=True, index=True)
    feed_id = Column(Integer, ForeignKey("calendar_feeds.id", ondelete="CASCADE"), nullable=True)
    uid = Column(String(255), index=True, nullable=False)
    title = Column(String(300), nullable=False)
    description = Column(Text, default="", nullable=False)
    location = Column(String(255), default="", nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    category = Column(String(50), default="INNE", nullable=False)  # KOLOKWIUM | EGZAMIN | DEADLINE_RAU2 | WYKLAD | LAB
    source_label = Column(String(100), default="USOS", nullable=False)
    target_group = Column(String(60), default="Wszystkie", nullable=False)

    feed = relationship("CalendarFeed", back_populates="events")


class Announcement(Base):
    __tablename__ = "announcements"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(255), nullable=False)
    content = Column(Text, default="", nullable=False)
    priority = Column(String(30), default="NORMAL", nullable=False)  # LOW | NORMAL | HIGH | CRITICAL
    due_date = Column(DateTime(timezone=True), nullable=True)
    course_name = Column(String(150), default="", nullable=False)
    completed_groups = Column(String(500), default="", nullable=False)  # CSV np. "1,2,Lab 1A"
    created_by = Column(String(255), default="", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
