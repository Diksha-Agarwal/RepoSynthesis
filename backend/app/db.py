from pathlib import Path

from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker


_APP_DIR = Path(__file__).parent
DATA_DIR = _APP_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

_DB_PATH = str((DATA_DIR / "app.db").resolve()).replace("\\", "/")
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


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


Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
