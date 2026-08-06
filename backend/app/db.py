from sqlalchemy import create_engine, Column, Integer, String, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import relationship
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# Use absolute path so DB is always in backend/app/data/ regardless of working directory
_APP_DIR = Path(__file__).parent
_DATA_DIR = _APP_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

# Always use absolute path for SQLite to avoid CWD-dependent issues
_DB_PATH = str((_DATA_DIR / "app.db").resolve()).replace("\\", "/")
DATABASE_URL = f"sqlite:///{_DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    hashed_password = Column(String)
    is_admin = Column(Integer, default=0)

class Project(Base):
    __tablename__ = "projects"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey('users.id', ondelete="CASCADE"))
    name = Column(String, index=True)
    github_url = Column(String, nullable=True)
    zip_filename = Column(String, nullable=True)
    personas = Column(String, default="SDE,PM")  # comma-separated
    depth = Column(String, default="standard")   # quick/standard/deep
    verbosity = Column(String, default="medium")  # low/medium/high

    user = relationship("User", back_populates="projects")

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


User.projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")