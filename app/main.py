import base64
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

from app.auth import (
    COOKIE_NAME,
    create_access_token,
    get_current_user,
    hash_password,
    require_roles,
    seed_initial_data,
    verify_password,
)
from app.config import settings
from app.database import Base, SessionLocal, engine, get_db
from app.models import (
    Announcement,
    CalendarEvent,
    CalendarFeed,
    Course,
    RoleEnum,
    Student,
    User,
)
from app.schemas import (
    AnnouncementCreate,
    AnnouncementOut,
    AnnouncementToggleGroup,
    CalendarEventOut,
    CalendarFeedCreate,
    CalendarFeedOut,
    CourseCreate,
    CourseOut,
    CourseUpdate,
    ImportResult,
    LoginRequest,
    MailSendRequest,
    MailSendResult,
    ManualEventCreate,
    PasswordChangeRequest,
    StudentBulkAction,
    StudentCreate,
    StudentInlineUpdate,
    StudentOut,
    UserCreate,
    UserOut,
    UserUpdate,
)
from app.services import (
    CLASS_SCHEDULE_CATEGORIES,
    TIMELINE_CATEGORIES,
    export_students_to_csv,
    export_students_to_xlsx,
    import_students_from_bytes,
    parse_ics_content,
    send_personalized_emails,
    sync_single_calendar_feed,
)


def seed_demo_academic_data(db: Session) -> None:
    """Tworzy startowych studentów, przedmioty RAU2 oraz przykładowe ogłoszenia przy pierwszym uruchomieniu."""
    if db.query(Student).count() == 0:
        initial_students = [
            Student(
                imie="Kamil",
                nazwisko="Zieliński",
                email="kamil.zielinski@student.polsl.pl",
                grupa="1",
                komentarz="starosta grupy 1 | rozliczony",
            ),
            Student(
                imie="Aleksandra",
                nazwisko="Kaczmarek",
                email="aleksandra.kaczmarek@student.polsl.pl",
                grupa="1",
                komentarz="Lab 1A | rozliczony",
            ),
            Student(
                imie="Michał",
                nazwisko="Woźniak",
                email="michal.wozniak@student.polsl.pl",
                grupa="2",
                komentarz="starosta grupy 2 | IOS",
            ),
            Student(
                imie="Natalia",
                nazwisko="Mazur",
                email="natalia.mazur@student.polsl.pl",
                grupa="2",
                komentarz="Lab 2B",
            ),
            Student(
                imie="Bartosz",
                nazwisko="Krawczyk",
                email="bartosz.krawczyk@student.polsl.pl",
                grupa="3",
                komentarz="starosta grupy 3 | koło naukowe AI",
            ),
        ]
        db.add_all(initial_students)
        db.commit()

    if db.query(Course).count() == 0:
        initial_courses = [
            Course(
                code="RAU2-SI",
                name="Sztuczna Inteligencja i Systemy Ekspertowe",
                lecturer="dr hab. inż. Jan Kowalski, prof. PŚ",
                rau2_url="https://platforma.polsl.pl/rau2/course/view.php?id=101",
                usos_url="https://usosweb.polsl.pl/kontroler.php?_action=katalog2/przedmioty/pokazPrzedmiot&prz_kod=RAU2-SI",
                passing_rules="Kolokwium zaliczeniowe (50%) + Projekt laboratoryjny na platformie RAU2 (50%). Obecność obowiązkowa na lab.",
                assigned_groups="Wszystkie (Grupy 1, 2, 3)",
                ects=5,
            ),
            Course(
                code="RAU2-SA",
                name="Systemy Automatyki i Robotyki Przemysłowej",
                lecturer="dr inż. Piotr Nowak",
                rau2_url="https://platforma.polsl.pl/rau2/course/view.php?id=102",
                usos_url="https://usosweb.polsl.pl/kontroler.php?_action=katalog2/przedmioty/pokazPrzedmiot&prz_kod=RAU2-SA",
                passing_rules="Egzamin pisemny w sesji + zaliczenie 6 sprawozdań na Moodle RAU2 w terminie 7 dni od zajęć.",
                assigned_groups="Wszystkie (Lab 1A, 1B, 2A, 2B, 3A)",
                ects=6,
            ),
            Course(
                code="RAU2-SW",
                name="Systemy Wbudowane i Mikrokontrolery STM32",
                lecturer="dr inż. Marek Wiśniewski",
                rau2_url="https://platforma.polsl.pl/rau2/course/view.php?id=103",
                usos_url="https://usosweb.polsl.pl/kontroler.php?_action=katalog2/przedmioty/pokazPrzedmiot&prz_kod=RAU2-SW",
                passing_rules="Projekt praktyczny + obrona kodu w ostatnim tygodniu semestru.",
                assigned_groups="Grupa 1, Grupa 2, Grupa 3",
                ects=4,
            ),
        ]
        db.add_all(initial_courses)
        db.commit()

    if db.query(Announcement).count() == 0:
        now = datetime.now(timezone.utc)
        initial_announcements = [
            Announcement(
                title="Zbiórka sprawozdań Lab #2 na platformie RAU2 (Sztuczna Inteligencja)",
                content="Pamiętajcie o wgraniu sprawozdania w formacie PDF oraz kodu źródłowego przed północą. Starostowie grup proszeni o potwierdzenie kompletu.",
                priority="HIGH",
                due_date=now + timedelta(days=4),
                course_name="Sztuczna Inteligencja i Systemy Ekspertowe",
                completed_groups="1",
                created_by=settings.ADMIN_FULL_NAME,
            ),
            Announcement(
                title="Ustalenie terminu zerowego z Systemów Automatyki",
                content="Prowadzący zaproponował termin zerowy przed sesją. Proszę starostów grup o zebranie głosów do piątku.",
                priority="CRITICAL",
                due_date=now + timedelta(days=7),
                course_name="Systemy Automatyki i Robotyki Przemysłowej",
                completed_groups="1,2",
                created_by=settings.ADMIN_FULL_NAME,
            ),
        ]
        db.add_all(initial_announcements)
        db.commit()

    if db.query(CalendarEvent).count() == 0:
        now = datetime.now(timezone.utc)
        # Wyznaczamy początek bieżącego tygodnia (poniedziałek godz. 08:00 UTC) dla czytelnego rozkładu w Kalendarzu
        monday = (now - timedelta(days=now.weekday())).replace(hour=8, minute=0, second=0, microsecond=0)
        initial_events = [
            CalendarEvent(
                feed_id=None,
                uid=f"seed-1-{uuid.uuid4()}",
                title="Kolokwium #1 - Sztuczna Inteligencja (Sala 310 AEiI)",
                description="Zakres: przeszukiwanie przestrzeni stanów, algorytm A*, sieci neuronowe MLP.",
                location="Wydział AEiI, Aula B / Sala 310",
                start_time=now + timedelta(days=5, hours=10),
                end_time=now + timedelta(days=5, hours=12),
                category="KOLOKWIUM",
                source_label="USOSweb RAU2",
                target_group="Wszystkie",
            ),
            CalendarEvent(
                feed_id=None,
                uid=f"seed-2-{uuid.uuid4()}",
                title="Deadline Moodle RAU2: Oddanie sprawozdania Lab 2",
                description="Wymagany plik PDF na platforma.polsl.pl/rau2",
                location="platforma.polsl.pl/rau2",
                start_time=now + timedelta(days=3, hours=23),
                end_time=now + timedelta(days=3, hours=23, minutes=59),
                category="DEADLINE_RAU2",
                source_label="Moodle RAU2",
                target_group="Wszystkie",
            ),
            CalendarEvent(
                feed_id=None,
                uid=f"seed-3-{uuid.uuid4()}",
                title="Sztuczna Inteligencja i Systemy Ekspertowe [Wykład]",
                description="Wykład kursowy dla całego roku RAU2.",
                location="Wydział AEiI, Aula A",
                start_time=monday.replace(hour=8, minute=30),
                end_time=monday.replace(hour=10, minute=0),
                category="WYKLAD",
                source_label="USOSweb Plan",
                target_group="Wszystkie",
            ),
            CalendarEvent(
                feed_id=None,
                uid=f"seed-4-{uuid.uuid4()}",
                title="Systemy Automatyki i Robotyki [Laboratorium]",
                description="Ćwiczenia laboratoryjne - sterowniki PLC.",
                location="Wydział AEiI, Sala Lab 214",
                start_time=(monday + timedelta(days=1)).replace(hour=10, minute=15),
                end_time=(monday + timedelta(days=1)).replace(hour=12, minute=30),
                category="LAB",
                source_label="USOSweb Plan",
                target_group="1",
            ),
            CalendarEvent(
                feed_id=None,
                uid=f"seed-5-{uuid.uuid4()}",
                title="Język Angielski Specjalistyczny B2+ [Lektorat]",
                description="Lektorat SPNJO dla kierunku AEiI.",
                location="SPNJO Gliwice, Sala 105",
                start_time=(monday + timedelta(days=2)).replace(hour=12, minute=0),
                end_time=(monday + timedelta(days=2)).replace(hour=13, minute=30),
                category="LEKTORAT",
                source_label="USOSweb Plan",
                target_group="Wszystkie",
            ),
            CalendarEvent(
                feed_id=None,
                uid=f"seed-6-{uuid.uuid4()}",
                title="Systemy Wbudowane STM32 [Projekt]",
                description="Konsultacje projektowe i odbiór płytek Nucleo.",
                location="Wydział AEiI, Sala 412",
                start_time=(monday + timedelta(days=3)).replace(hour=14, minute=0),
                end_time=(monday + timedelta(days=3)).replace(hour=15, minute=30),
                category="PROJEKT",
                source_label="USOSweb Plan",
                target_group="2",
            ),
        ]
        db.add_all(initial_events)
        db.commit()


def ensure_schema_migrations(db: Session) -> None:
    """Dodaje nowe kolumny (np. avatar_url) do istniejącej bazy SQLite bez utraty danych."""
    try:
        db.execute(text("ALTER TABLE users ADD COLUMN avatar_url TEXT"))
        db.commit()
    except Exception:
        db.rollback()


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        ensure_schema_migrations(db)
        seed_initial_data(db)
        seed_demo_academic_data(db)
    finally:
        db.close()
    yield


app = FastAPI(
    title="Starosta Hub - Politechnika Śląska AEiI (RAU2)",
    description="Panel zarządzania rokiem akademickim, bazą studentów, komunikacją Office 365 oraz integracją USOSweb & RAU2.",
    version="1.0.0",
    lifespan=lifespan,
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


# =====================================================================
# 1. ENDPOINTY AUTORYZACJI I ZARZĄDZANIA UŻYTKOWNIKAMI (RBAC)
# =====================================================================
@app.post("/api/auth/login", response_model=UserOut)
def login(payload: LoginRequest, response: Response, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if not user or not verify_password(payload.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowy adres email lub hasło.",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Konto zostało zablokowane przez Starostę Roku.",
        )

    token = create_access_token({"sub": str(user.id), "role": user.role})
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        path="/",
    )
    return user


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"message": "Wylogowano pomyślnie."}


@app.get("/api/auth/me", response_model=UserOut)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@app.post("/api/auth/change-password")
def change_own_password(
    payload: PasswordChangeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Aktualne hasło jest nieprawidłowe.")
    current_user.hashed_password = hash_password(payload.new_password)
    current_user.must_change_password = False
    db.commit()
    return {"message": "Hasło zostało zmienione."}


@app.post("/api/auth/avatar", response_model=UserOut)
async def upload_profile_avatar(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(
            status_code=400,
            detail="Dozwolone są wyłącznie pliki graficzne (PNG, JPG, WEBP, GIF).",
        )
    content = await file.read()
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail="Plik zdjęcia profilowego jest zbyt duży (maksymalnie 4 MB).",
        )

    encoded = base64.b64encode(content).decode("ascii")
    data_uri = f"data:{file.content_type};base64,{encoded}"
    current_user.avatar_url = data_uri
    db.commit()
    db.refresh(current_user)
    return current_user


@app.delete("/api/auth/avatar", response_model=UserOut)
def delete_profile_avatar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    current_user.avatar_url = None
    db.commit()
    db.refresh(current_user)
    return current_user


@app.get("/api/users", response_model=List[UserOut])
def list_users(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN)),
):
    return db.query(User).order_by(User.id.asc()).all()


@app.post("/api/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def create_user(
    payload: UserCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN)),
):
    email = payload.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(status_code=400, detail="Użytkownik z tym adresem email już istnieje.")

    new_user = User(
        email=email,
        full_name=payload.full_name.strip(),
        hashed_password=hash_password(payload.password),
        role=payload.role.value,
        assigned_group=(payload.assigned_group or "Wszystkie").strip(),
        is_active=True,
        must_change_password=True,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    return new_user


@app.patch("/api/users/{user_id}", response_model=UserOut)
def update_user(
    user_id: int,
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_roles(RoleEnum.ADMIN)),
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nie znaleziono użytkownika.")

    if user.id == current_admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="Nie możesz dezaktywować własnego konta Głównego Administratora.")

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip()
    if payload.role is not None:
        if user.id == current_admin.id and payload.role != RoleEnum.ADMIN:
            raise HTTPException(status_code=400, detail="Nie możesz odebrać sobie roli ADMIN.")
        user.role = payload.role.value
    if payload.assigned_group is not None:
        user.assigned_group = payload.assigned_group.strip()
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.temporary_password:
        if len(payload.temporary_password) < 6:
            raise HTTPException(status_code=400, detail="Hasło tymczasowe musi mieć min. 6 znaków.")
        user.hashed_password = hash_password(payload.temporary_password)
        user.must_change_password = True

    db.commit()
    db.refresh(user)
    return user


@app.delete("/api/users/{user_id}")
def delete_user(
    user_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(require_roles(RoleEnum.ADMIN)),
):
    if user_id == current_admin.id:
        raise HTTPException(status_code=400, detail="Nie możesz usunąć własnego konta Głównego Administratora.")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Nie znaleziono użytkownika.")
    db.delete(user)
    db.commit()
    return {"message": "Użytkownik został usunięty."}


# =====================================================================
# 2. BAZA STUDENTÓW, FILTROWANIE, EDYCJA INLINE, IMPORT/EKSPORT EXCEL
# =====================================================================
@app.get("/api/students", response_model=List[StudentOut])
def list_students(
    grupa: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Student)
    if grupa and grupa != "ALL":
        query = query.filter(Student.grupa == grupa)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.imie.ilike(term),
                Student.nazwisko.ilike(term),
                Student.email.ilike(term),
                Student.komentarz.ilike(term),
                Student.grupa.ilike(term),
            )
        )
    return query.order_by(Student.grupa.asc(), Student.nazwisko.asc(), Student.imie.asc()).all()


@app.get("/api/students/groups", response_model=List[str])
def list_student_groups(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = db.query(Student.grupa).distinct().order_by(Student.grupa.asc()).all()
    return [r[0] for r in rows if r[0]]


@app.post("/api/students", response_model=StudentOut, status_code=status.HTTP_201_CREATED)
def create_student(
    payload: StudentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    email = payload.email.strip().lower()
    existing = db.query(Student).filter(Student.email == email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Student z tym adresem email już istnieje w bazie.")

    student = Student(
        imie=payload.imie.strip(),
        nazwisko=payload.nazwisko.strip(),
        email=email,
        grupa=payload.grupa.strip(),
        komentarz=payload.komentarz.strip(),
    )
    db.add(student)
    db.commit()
    db.refresh(student)
    return student


@app.patch("/api/students/{student_id}", response_model=StudentOut)
def update_student_inline(
    student_id: int,
    payload: StudentInlineUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Nie znaleziono studenta.")

    if payload.email is not None:
        new_email = payload.email.strip().lower()
        conflict = (
            db.query(Student)
            .filter(Student.email == new_email, Student.id != student_id)
            .first()
        )
        if conflict:
            raise HTTPException(status_code=400, detail="Ten adres email jest już przypisany innemu studentowi.")
        student.email = new_email

    if payload.imie is not None:
        student.imie = payload.imie.strip()
    if payload.nazwisko is not None:
        student.nazwisko = payload.nazwisko.strip()
    if payload.grupa is not None:
        student.grupa = payload.grupa.strip()
    if payload.komentarz is not None:
        student.komentarz = payload.komentarz.strip()

    db.commit()
    db.refresh(student)
    return student


@app.delete("/api/students/{student_id}")
def delete_student(
    student_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    student = db.query(Student).filter(Student.id == student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Nie znaleziono studenta.")
    db.delete(student)
    db.commit()
    return {"message": "Rekord studenta został usunięty."}


@app.post("/api/students/bulk")
def bulk_students_action(
    payload: StudentBulkAction,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    if not payload.student_ids:
        raise HTTPException(status_code=400, detail="Nie wybrano żadnych studentów.")

    students = db.query(Student).filter(Student.id.in_(payload.student_ids)).all()
    affected = len(students)

    if payload.action == "DELETE":
        for s in students:
            db.delete(s)
    elif payload.action == "SET_GROUP":
        if not payload.value or not payload.value.strip():
            raise HTTPException(status_code=400, detail="Podaj docelową nazwę grupy.")
        for s in students:
            s.grupa = payload.value.strip()
    elif payload.action == "APPEND_COMMENT":
        if not payload.value or not payload.value.strip():
            raise HTTPException(status_code=400, detail="Podaj treść dopisywanego komentarza.")
        note = payload.value.strip()
        for s in students:
            s.komentarz = f"{s.komentarz} | {note}".strip(" |") if s.komentarz else note
    elif payload.action == "CLEAR_COMMENT":
        for s in students:
            s.komentarz = ""
    else:
        raise HTTPException(status_code=400, detail=f"Nieznana akcja masowa: {payload.action}")

    db.commit()
    return {"affected": affected, "action": payload.action}


@app.post("/api/students/import", response_model=ImportResult)
async def import_students_endpoint(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Brak nazwy pliku.")
    content = await file.read()
    try:
        return import_students_from_bytes(db, file.filename, content)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Błąd podczas importu pliku: {exc}")


@app.get("/api/students/export")
def export_students_endpoint(
    format: str = Query("xlsx", pattern="^(xlsx|csv)$"),
    grupa: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Student)
    if grupa and grupa != "ALL":
        query = query.filter(Student.grupa == grupa)
    if search and search.strip():
        term = f"%{search.strip()}%"
        query = query.filter(
            or_(
                Student.imie.ilike(term),
                Student.nazwisko.ilike(term),
                Student.email.ilike(term),
                Student.komentarz.ilike(term),
            )
        )
    students = query.order_by(Student.grupa.asc(), Student.nazwisko.asc()).all()

    if format == "csv":
        data = export_students_to_csv(students)
        return StreamingResponse(
            iter([data]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="studenci_rau2.csv"'},
        )

    data = export_students_to_xlsx(students)
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="studenci_rau2.xlsx"'},
    )


# =====================================================================
# 3. MODUŁ POCZTY (OUTLOOK / OFFICE 365 SMTP)
# =====================================================================
@app.get("/api/mail/config")
def get_mail_config(_: User = Depends(get_current_user)):
    return {
        "smtp_host": settings.SMTP_HOST,
        "smtp_port": settings.SMTP_PORT,
        "smtp_user": settings.SMTP_USER,
        "smtp_from_name": settings.SMTP_FROM_NAME,
        "is_configured": bool(settings.SMTP_USER and settings.SMTP_PASSWORD),
    }


@app.post("/api/mail/send", response_model=MailSendResult)
def send_mail_endpoint(
    payload: MailSendRequest,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    query = db.query(Student)
    if payload.recipient_ids:
        query = query.filter(Student.id.in_(payload.recipient_ids))
    elif payload.target_group and payload.target_group != "ALL":
        query = query.filter(Student.grupa == payload.target_group)

    recipients = query.all()
    if not recipients:
        raise HTTPException(status_code=400, detail="Brak odbiorców spełniających kryteria wysyłki.")

    return send_personalized_emails(recipients, payload.subject, payload.body_template)


# =====================================================================
# 4. INTEGRACJA USOSWEB & RAU2: KATALOG PRZEDMIOTÓW, KALENDARZ .ICS, OGŁOSZENIA
# =====================================================================
@app.get("/api/courses", response_model=List[CourseOut])
def list_courses(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(Course).order_by(Course.code.asc()).all()


@app.post("/api/courses", response_model=CourseOut, status_code=status.HTTP_201_CREATED)
def create_course(
    payload: CourseCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    course = Course(**payload.model_dump())
    db.add(course)
    db.commit()
    db.refresh(course)
    return course


@app.patch("/api/courses/{course_id}", response_model=CourseOut)
def update_course(
    course_id: int,
    payload: CourseUpdate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu.")
    for field, val in payload.model_dump(exclude_unset=True).items():
        setattr(course, field, val)
    db.commit()
    db.refresh(course)
    return course


@app.delete("/api/courses/{course_id}")
def delete_course(
    course_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    course = db.query(Course).filter(Course.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Nie znaleziono przedmiotu.")
    db.delete(course)
    db.commit()
    return {"message": "Przedmiot został usunięty."}


# --- Kalendarze .ics (USOSweb & RAU2 Moodle) ---
@app.get("/api/calendar/feeds", response_model=List[CalendarFeedOut])
def list_calendar_feeds(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(CalendarFeed).order_by(CalendarFeed.id.desc()).all()


@app.post("/api/calendar/feeds", response_model=CalendarFeedOut, status_code=status.HTTP_201_CREATED)
def add_calendar_feed(
    payload: CalendarFeedCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    feed = CalendarFeed(
        name=payload.name.strip(),
        source_type=payload.source_type,
        ics_url=payload.ics_url.strip(),
        target_group=payload.target_group.strip(),
        is_active=True,
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)

    # Próba natychmiastowej synchronizacji po podpięciu
    sync_single_calendar_feed(db, feed)
    db.refresh(feed)
    return feed


@app.post("/api/calendar/feeds/upload-ics")
async def upload_ics_file(
    name: str = Query(..., description="Nazwa źródła np. USOSweb Semestr Zimowy"),
    source_type: str = Query("USOS"),
    target_group: str = Query("Wszystkie"),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    content = await file.read()
    feed = CalendarFeed(
        name=name,
        source_type=source_type,
        ics_url=f"local-upload://{file.filename}",
        target_group=target_group,
        is_active=True,
        last_synced_at=datetime.now(timezone.utc),
    )
    db.add(feed)
    db.commit()
    db.refresh(feed)

    try:
        events = parse_ics_content(content, feed)
        for ev in events:
            db.add(ev)
        db.commit()
        return {"message": f"Zaimportowano {len(events)} wydarzeń z pliku .ics", "events_count": len(events)}
    except Exception as exc:
        db.delete(feed)
        db.commit()
        raise HTTPException(status_code=400, detail=f"Nieprawidłowy plik .ics: {exc}")


@app.post("/api/calendar/sync")
def sync_all_feeds(
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    feeds = db.query(CalendarFeed).filter(CalendarFeed.is_active == True).all()
    total_events = 0
    errors = []
    synced_feeds = 0

    for feed in feeds:
        if feed.ics_url.startswith("local-upload://"):
            continue
        ok, count, msg = sync_single_calendar_feed(db, feed)
        if ok:
            synced_feeds += 1
            total_events += count
        else:
            errors.append(msg)

    return {
        "synced_feeds": synced_feeds,
        "total_events": total_events,
        "errors": errors,
    }


@app.delete("/api/calendar/feeds/{feed_id}")
def delete_calendar_feed(
    feed_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    feed = db.query(CalendarFeed).filter(CalendarFeed.id == feed_id).first()
    if not feed:
        raise HTTPException(status_code=404, detail="Nie znaleziono subskrypcji kalendarza.")
    db.delete(feed)
    db.commit()
    return {"message": "Subskrypcja kalendarza oraz powiązane wydarzenia zostały usunięte."}


@app.get("/api/calendar/events", response_model=List[CalendarEventOut])
def list_calendar_events(
    upcoming_only: bool = Query(False),
    category: Optional[str] = Query(None),
    mode: Optional[str] = Query(None, description="'timeline' wyklucza zwykłe zajęcia (wykłady, laby, lektoraty)"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(CalendarEvent)
    if mode == "timeline":
        query = query.filter(~CalendarEvent.category.in_(list(CLASS_SCHEDULE_CATEGORIES)))
    elif mode == "classes":
        query = query.filter(CalendarEvent.category.in_(list(CLASS_SCHEDULE_CATEGORIES)))

    if upcoming_only:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
        query = query.filter(CalendarEvent.start_time >= cutoff)
    if category and category != "ALL":
        query = query.filter(CalendarEvent.category == category)
    return query.order_by(CalendarEvent.start_time.asc()).limit(500).all()


@app.post("/api/calendar/events", response_model=CalendarEventOut, status_code=status.HTTP_201_CREATED)
def create_manual_event(
    payload: ManualEventCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    ev = CalendarEvent(
        feed_id=None,
        uid=f"manual-{uuid.uuid4()}",
        title=payload.title.strip(),
        description=payload.description.strip(),
        location=payload.location.strip(),
        start_time=payload.start_time,
        end_time=payload.end_time,
        category=payload.category,
        source_label=payload.source_label,
        target_group=payload.target_group,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


@app.delete("/api/calendar/events/{event_id}")
def delete_calendar_event(
    event_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    ev = db.query(CalendarEvent).filter(CalendarEvent.id == event_id).first()
    if not ev:
        raise HTTPException(status_code=404, detail="Nie znaleziono wydarzenia.")
    db.delete(ev)
    db.commit()
    return {"message": "Wydarzenie usunięte."}


# --- Tablica Ogłoszeń i Śledzenie Deadlinów dla Grup ---
@app.get("/api/announcements", response_model=List[AnnouncementOut])
def list_announcements(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return db.query(Announcement).order_by(Announcement.created_at.desc()).all()


@app.post("/api/announcements", response_model=AnnouncementOut, status_code=status.HTTP_201_CREATED)
def create_announcement(
    payload: AnnouncementCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    ann = Announcement(
        title=payload.title.strip(),
        content=payload.content.strip(),
        priority=payload.priority,
        due_date=payload.due_date,
        course_name=payload.course_name.strip(),
        completed_groups=payload.completed_groups.strip(),
        created_by=current_user.full_name,
    )
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann


@app.post("/api/announcements/{ann_id}/toggle-group", response_model=AnnouncementOut)
def toggle_announcement_group(
    ann_id: int,
    payload: AnnouncementToggleGroup,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Nie znaleziono ogłoszenia/zadania.")

    grp = payload.group_name.strip()
    current_groups = [g.strip() for g in ann.completed_groups.split(",") if g.strip()]
    if grp in current_groups:
        current_groups.remove(grp)
    else:
        current_groups.append(grp)

    ann.completed_groups = ",".join(current_groups)
    db.commit()
    db.refresh(ann)
    return ann


@app.delete("/api/announcements/{ann_id}")
def delete_announcement(
    ann_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_roles(RoleEnum.ADMIN, RoleEnum.GROUP_LEADER)),
):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(status_code=404, detail="Nie znaleziono ogłoszenia.")
    db.delete(ann)
    db.commit()
    return {"message": "Ogłoszenie zostało usunięte."}


# =====================================================================
# 5. SERWOWANIE FRONTENDU (REACT + TAILWIND DASHBOARD)
# =====================================================================
@app.get("/", response_class=HTMLResponse)
def serve_spa():
    index_path = os.path.join(STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse(
        "<h1>Starosta Hub Backend działa poprawnie. Trwa przygotowanie interfejsu frontendu (Krok 3)...</h1>"
    )
