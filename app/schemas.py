from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, EmailStr, Field
from app.models import RoleEnum


# ==================== AUTH & USERS ====================
class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(..., min_length=2, max_length=255)
    password: str = Field(..., min_length=6)
    role: RoleEnum = RoleEnum.GROUP_LEADER
    assigned_group: Optional[str] = None


class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[RoleEnum] = None
    assigned_group: Optional[str] = None
    is_active: Optional[bool] = None
    temporary_password: Optional[str] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=6)


class UserOut(BaseModel):
    id: int
    email: EmailStr
    full_name: str
    role: str
    assigned_group: Optional[str]
    avatar_url: Optional[str] = None
    is_active: bool
    must_change_password: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ==================== STUDENTS ====================
class StudentBase(BaseModel):
    imie: str = Field(..., min_length=1, max_length=120)
    nazwisko: str = Field(..., min_length=1, max_length=120)
    email: EmailStr
    grupa: str = Field(..., min_length=1, max_length=60)
    komentarz: str = ""


class StudentCreate(StudentBase):
    pass


class StudentInlineUpdate(BaseModel):
    imie: Optional[str] = None
    nazwisko: Optional[str] = None
    email: Optional[EmailStr] = None
    grupa: Optional[str] = None
    komentarz: Optional[str] = None


class StudentBulkAction(BaseModel):
    student_ids: List[int]
    action: str  # "SET_GROUP" | "APPEND_COMMENT" | "CLEAR_COMMENT" | "DELETE"
    value: Optional[str] = None


class StudentOut(StudentBase):
    id: int
    utworzono_data: datetime

    model_config = {"from_attributes": True}


class ImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    errors: List[str]


# ==================== MAIL / OUTLOOK ====================
class MailSendRequest(BaseModel):
    recipient_ids: Optional[List[int]] = None
    target_group: Optional[str] = None  # "ALL" lub nazwa grupy np. "1"
    subject: str = Field(..., min_length=2, max_length=255)
    body_template: str = Field(..., min_length=2)


class MailSendResult(BaseModel):
    sent_count: int
    failed_count: int
    errors: List[str]


# ==================== COURSES (RAU2 & USOS) ====================
class CourseCreate(BaseModel):
    code: str
    name: str
    lecturer: str = ""
    rau2_url: str = ""
    usos_url: str = ""
    passing_rules: str = ""
    assigned_groups: str = "Wszystkie"
    ects: int = 3


class CourseUpdate(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None
    lecturer: Optional[str] = None
    rau2_url: Optional[str] = None
    usos_url: Optional[str] = None
    passing_rules: Optional[str] = None
    assigned_groups: Optional[str] = None
    ects: Optional[int] = None


class CourseOut(CourseCreate):
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ==================== CALENDAR (.ICS) ====================
class CalendarFeedCreate(BaseModel):
    name: str
    source_type: str = "USOS"  # USOS | RAU2_MOODLE | CUSTOM
    ics_url: str
    target_group: str = "Wszystkie"


class CalendarFeedOut(BaseModel):
    id: int
    name: str
    source_type: str
    ics_url: str
    target_group: str
    is_active: bool
    last_synced_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class ManualEventCreate(BaseModel):
    title: str
    description: str = ""
    location: str = ""
    start_time: datetime
    end_time: Optional[datetime] = None
    category: str = "KOLOKWIUM"
    source_label: str = "Starosta RAU2"
    target_group: str = "Wszystkie"


class CalendarEventOut(BaseModel):
    id: int
    feed_id: Optional[int]
    uid: str
    title: str
    description: str
    location: str
    start_time: datetime
    end_time: Optional[datetime]
    category: str
    source_label: str
    target_group: str

    model_config = {"from_attributes": True}


# ==================== ANNOUNCEMENTS & DEADLINES ====================
class AnnouncementCreate(BaseModel):
    title: str
    content: str = ""
    priority: str = "NORMAL"
    due_date: Optional[datetime] = None
    course_name: str = ""
    completed_groups: str = ""


class AnnouncementToggleGroup(BaseModel):
    group_name: str


class AnnouncementOut(BaseModel):
    id: int
    title: str
    content: str
    priority: str
    due_date: Optional[datetime]
    course_name: str
    completed_groups: str
    created_by: str
    created_at: datetime

    model_config = {"from_attributes": True}
