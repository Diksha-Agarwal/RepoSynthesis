"""Centralized, validated backend configuration."""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple
from urllib.parse import urlsplit

from dotenv import load_dotenv


APP_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = APP_DIR.parent.parent
load_dotenv(REPOSITORY_ROOT / ".env")


def _read_int(name: str, default: int, errors: list[str], *, minimum: int = 1) -> int:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = int(raw_value)
    except ValueError:
        errors.append(f"{name} must be an integer")
        return default
    if value < minimum:
        errors.append(f"{name} must be at least {minimum}")
        return default
    return value


def _read_float(name: str, default: float, errors: list[str], *, minimum: float, maximum: float) -> float:
    raw_value = os.getenv(name)
    if raw_value is None or not raw_value.strip():
        return default
    try:
        value = float(raw_value)
    except ValueError:
        errors.append(f"{name} must be a number")
        return default
    if not minimum <= value <= maximum:
        errors.append(f"{name} must be between {minimum} and {maximum}")
        return default
    return value


def _read_origins(errors: list[str]) -> Tuple[str, ...]:
    raw_value = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = tuple(origin.strip().rstrip("/") for origin in raw_value.split(",") if origin.strip())
    if not origins:
        errors.append("CORS_ALLOWED_ORIGINS is required")
        return ("http://localhost:3000",)
    for origin in origins:
        parsed = urlsplit(origin)
        if (
            origin == "*"
            or parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            errors.append(f"CORS_ALLOWED_ORIGINS contains an invalid origin: {origin}")
    return origins


def _resolve_data_dir(raw_value: str, repository_root: Path) -> Path:
    path = Path(raw_value).expanduser()
    if not path.is_absolute():
        path = repository_root / path
    return path.resolve()


def _normalize_database_url(raw_value: str, repository_root: Path) -> str:
    if not raw_value.startswith("sqlite:///") or raw_value == "sqlite:///:memory:":
        return raw_value
    path_text = raw_value[len("sqlite:///"):]
    database_path = Path(path_text).expanduser()
    if not database_path.is_absolute():
        database_path = repository_root / database_path
    return f"sqlite:///{database_path.resolve().as_posix()}"


@dataclass(frozen=True)
class AppSettings:
    database_url: str
    redis_url: str
    rq_queue_name: str
    cors_allowed_origins: Tuple[str, ...]
    backend_host: str
    backend_port: int
    data_dir: Path
    max_upload_zip_bytes: int
    max_extracted_total_bytes: int
    max_extracted_files: int
    max_extracted_file_bytes: int
    max_zip_compression_ratio: int
    repository_clone_timeout_seconds: int
    github_validation_timeout_seconds: int
    preprocessing_job_timeout_seconds: int
    analysis_job_timeout_seconds: int
    job_retry_max: int
    job_retry_interval_seconds: int
    redis_connect_timeout_seconds: int
    redis_health_check_interval_seconds: int
    openai_api_key: str
    openai_model: str
    openai_chat_model: str
    openai_embedding_model: str
    openai_temperature: float
    openai_max_tokens: int
    openai_request_timeout_seconds: int
    log_level: str
    validation_errors: Tuple[str, ...]

    @property
    def is_valid(self) -> bool:
        return not self.validation_errors


def load_settings() -> AppSettings:
    errors: list[str] = []
    default_data_dir = APP_DIR / "data"

    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        errors.append("DATABASE_URL is required")
        database_url = f"sqlite:///{str((default_data_dir / 'app.db').resolve()).replace(chr(92), '/')}"
    else:
        database_url = _normalize_database_url(database_url, REPOSITORY_ROOT)

    redis_url = os.getenv("REDIS_URL", "").strip()
    if not redis_url:
        errors.append("REDIS_URL is required")
        redis_url = "redis://localhost:6379/0"
    elif urlsplit(redis_url).scheme not in {"redis", "rediss", "unix"}:
        errors.append("REDIS_URL must use redis://, rediss://, or unix://")

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_api_key or openai_api_key.lower().startswith(("your_", "replace_")):
        errors.append("OPENAI_API_KEY is required and must not be a placeholder")

    data_dir = _resolve_data_dir(os.getenv("DATA_DIR", str(default_data_dir)), REPOSITORY_ROOT)
    queue_name = os.getenv("RQ_QUEUE_NAME", "repo-analysis").strip()
    if not queue_name:
        errors.append("RQ_QUEUE_NAME must not be empty")
        queue_name = "repo-analysis"

    log_level = os.getenv("LOG_LEVEL", "INFO").strip().upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        errors.append("LOG_LEVEL must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        log_level = "INFO"

    return AppSettings(
        database_url=database_url,
        redis_url=redis_url,
        rq_queue_name=queue_name,
        cors_allowed_origins=_read_origins(errors),
        backend_host=os.getenv("BACKEND_HOST", "0.0.0.0").strip() or "0.0.0.0",
        backend_port=_read_int("BACKEND_PORT", 8000, errors),
        data_dir=data_dir,
        max_upload_zip_bytes=_read_int("MAX_UPLOAD_ZIP_BYTES", 100 * 1024 * 1024, errors),
        max_extracted_total_bytes=_read_int("MAX_EXTRACTED_TOTAL_BYTES", 500 * 1024 * 1024, errors),
        max_extracted_files=_read_int("MAX_EXTRACTED_FILES", 10_000, errors),
        max_extracted_file_bytes=_read_int("MAX_EXTRACTED_FILE_BYTES", 50 * 1024 * 1024, errors),
        max_zip_compression_ratio=_read_int("MAX_ZIP_COMPRESSION_RATIO", 200, errors),
        repository_clone_timeout_seconds=_read_int("REPOSITORY_CLONE_TIMEOUT_SECONDS", 120, errors),
        github_validation_timeout_seconds=_read_int("GITHUB_VALIDATION_TIMEOUT_SECONDS", 10, errors),
        preprocessing_job_timeout_seconds=_read_int("PREPROCESSING_JOB_TIMEOUT_SECONDS", 1800, errors),
        analysis_job_timeout_seconds=_read_int("ANALYSIS_JOB_TIMEOUT_SECONDS", 7200, errors),
        job_retry_max=_read_int("JOB_RETRY_MAX", 2, errors, minimum=0),
        job_retry_interval_seconds=_read_int("JOB_RETRY_INTERVAL_SECONDS", 30, errors, minimum=0),
        redis_connect_timeout_seconds=_read_int("REDIS_CONNECT_TIMEOUT_SECONDS", 5, errors),
        redis_health_check_interval_seconds=_read_int("REDIS_HEALTH_CHECK_INTERVAL_SECONDS", 30, errors),
        openai_api_key=openai_api_key,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        openai_chat_model=os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini",
        openai_embedding_model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-large").strip() or "text-embedding-3-large",
        openai_temperature=_read_float("OPENAI_TEMPERATURE", 0.3, errors, minimum=0.0, maximum=1.0),
        openai_max_tokens=_read_int("OPENAI_MAX_TOKENS", 4000, errors),
        openai_request_timeout_seconds=_read_int("OPENAI_REQUEST_TIMEOUT_SECONDS", 120, errors),
        log_level=log_level,
        validation_errors=tuple(errors),
    )


SETTINGS = load_settings()
