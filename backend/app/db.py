from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker


_APP_DIR = Path(__file__).parent
DATA_DIR = _APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_DB_PATH = str((DATA_DIR / "app.db").resolve()).replace("\\", "/")
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


@event.listens_for(engine, "connect")
def enable_sqlite_foreign_keys(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Project(Base):
    """A repository analysis project in the single-user demo application."""

    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    github_url = Column(String, nullable=True)
    zip_filename = Column(String, nullable=True)
    personas = Column(String, default="SDE,PM", nullable=False)
    depth = Column(String, default="standard", nullable=False)
    verbosity = Column(String, default="medium", nullable=False)

    analysis_runs = relationship("AnalysisRun", back_populates="project", cascade="all, delete-orphan")


class AnalysisRun(Base):
    """Persistent state for one preprocessing or multi-agent analysis execution."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint("run_type IN ('preprocessing', 'analysis')", name="ck_analysis_runs_type"),
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'cancelled')",
            name="ck_analysis_runs_status",
        ),
        CheckConstraint("progress >= 0 AND progress <= 100", name="ck_analysis_runs_progress"),
        Index("ix_analysis_runs_project_created", "project_id", "created_at"),
        Index(
            "uq_analysis_runs_active_type",
            "project_id",
            "run_type",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
        ),
    )

    id = Column(String(36), primary_key=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True)
    run_type = Column(String(20), nullable=False)
    status = Column(String(20), nullable=False, default="queued", index=True)
    progress = Column(Integer, nullable=False, default=0)
    current_activity = Column(String(500), nullable=True)
    error_message = Column(Text, nullable=True)
    configuration = Column(JSON, nullable=False, default=dict)
    logs = Column(JSON, nullable=False, default=list)
    agent_insights = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    project = relationship("Project", back_populates="analysis_runs")


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
