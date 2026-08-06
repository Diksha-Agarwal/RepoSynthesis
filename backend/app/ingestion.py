"""Security controls for repository ingestion."""

import os
import re
import shutil
import stat
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import urlsplit

import requests
from settings import SETTINGS


class IngestionError(ValueError):
    def __init__(self, code: str, message: str, status_code: int = 400):
        super().__init__(message)
        self.code = code
        self.status_code = status_code

    def as_detail(self) -> dict:
        return {"code": self.code, "message": str(self)}


_OWNER_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")
_REPO_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
_WINDOWS_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}


def validate_project_id(project_id: int) -> int:
    if isinstance(project_id, bool):
        raise IngestionError("invalid_project_id", "Project ID must be a positive integer")
    try:
        numeric_project_id = int(project_id)
    except (TypeError, ValueError) as exc:
        raise IngestionError("invalid_project_id", "Project ID must be a positive integer") from exc
    if numeric_project_id <= 0 or str(project_id) != str(numeric_project_id):
        raise IngestionError("invalid_project_id", "Project ID must be a positive integer")
    return numeric_project_id


def validate_github_url(url: str) -> str:
    if url != url.strip() or any(ord(character) < 32 for character in url):
        raise IngestionError("invalid_github_url", "GitHub URL must not contain whitespace or control characters", 422)
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise IngestionError("invalid_github_url", "GitHub URL is malformed", 422) from exc

    if parsed.scheme != "https":
        raise IngestionError("invalid_github_url", "GitHub URL must use HTTPS", 422)
    if parsed.hostname is None or parsed.hostname.lower() != "github.com" or port is not None:
        raise IngestionError("invalid_github_url", "Only github.com repository URLs are accepted", 422)
    if parsed.username or parsed.password:
        raise IngestionError("invalid_github_url", "GitHub URL must not contain credentials", 422)
    if parsed.query or parsed.fragment:
        raise IngestionError("invalid_github_url", "GitHub URL must not contain query parameters or fragments", 422)
    if "%" in parsed.path or "\\" in parsed.path or parsed.path.endswith("/"):
        raise IngestionError("invalid_github_url", "Use the exact format https://github.com/{owner}/{repo}", 422)

    path_parts = parsed.path.split("/")
    if len(path_parts) != 3 or not path_parts[1] or not path_parts[2]:
        raise IngestionError("invalid_github_url", "Use the exact format https://github.com/{owner}/{repo}", 422)
    owner, repository = path_parts[1], path_parts[2]
    if not _OWNER_PATTERN.fullmatch(owner) or not _REPO_PATTERN.fullmatch(repository) or repository.lower().endswith(".git"):
        raise IngestionError("invalid_github_url", "GitHub owner or repository name is invalid", 422)
    return f"https://github.com/{owner}/{repository}"


def require_public_github_repository(url: str) -> str:
    canonical_url = validate_github_url(url)
    owner, repository = canonical_url[len("https://github.com/"):].split("/", 1)
    api_url = f"https://api.github.com/repos/{owner}/{repository}"
    try:
        response = requests.get(
            api_url,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "RepoResearchAI-demo"},
            timeout=SETTINGS.github_validation_timeout_seconds,
            allow_redirects=False,
        )
    except requests.Timeout as exc:
        raise IngestionError("github_validation_timeout", "Timed out while validating the GitHub repository", 504) from exc
    except requests.RequestException as exc:
        raise IngestionError("github_validation_failed", "Could not validate the GitHub repository", 502) from exc

    if response.status_code == 404:
        raise IngestionError("github_repository_unavailable", "GitHub repository was not found or is not public", 422)
    if response.status_code != 200:
        raise IngestionError("github_validation_failed", "GitHub could not validate the repository at this time", 502)
    try:
        repository_data = response.json()
    except ValueError as exc:
        raise IngestionError("github_validation_failed", "GitHub returned an invalid validation response", 502) from exc
    if repository_data.get("private") is not False:
        raise IngestionError("github_repository_unavailable", "Only public GitHub repositories are accepted", 422)
    return canonical_url


def resolve_uploaded_zip(path: str) -> Path:
    upload_root = (SETTINGS.data_dir / "uploads").resolve()
    supplied_path = Path(path)
    if supplied_path.is_symlink():
        raise IngestionError("unsafe_upload_path", "Uploaded ZIP path must not be a symbolic link")
    candidate = supplied_path.resolve()
    try:
        candidate.relative_to(upload_root)
    except ValueError as exc:
        raise IngestionError("unsafe_upload_path", "Uploaded ZIP path is outside the server upload directory") from exc
    if candidate.suffix.lower() != ".zip" or not candidate.is_file():
        raise IngestionError("invalid_zip", "Uploaded ZIP file is missing or invalid")
    return candidate


def _safe_member_path(member_name: str) -> PurePosixPath:
    normalized_name = member_name.replace("\\", "/")
    if not normalized_name or "\x00" in normalized_name or len(normalized_name) > 4096:
        raise IngestionError("suspicious_zip", "ZIP archive contains an invalid path")
    path_text = normalized_name[:-1] if normalized_name.endswith("/") else normalized_name
    raw_parts = path_text.split("/")
    path = PurePosixPath(path_text)
    if path.is_absolute() or any(part in ("", ".", "..") for part in raw_parts):
        raise IngestionError("unsafe_zip_path", "ZIP archive contains a path that escapes the extraction directory")
    if len(path.parts) > 50:
        raise IngestionError("suspicious_zip", "ZIP archive contains an excessively deep path")
    for part in path.parts:
        stem = part.split(".", 1)[0].upper()
        if len(part) > 255 or ":" in part or part.endswith((" ", ".")) or stem in _WINDOWS_RESERVED_NAMES:
            raise IngestionError("suspicious_zip", "ZIP archive contains an unsafe filename")
    return path


def inspect_zip_archive(zip_path: Path) -> None:
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            members = archive.infolist()
            files = [member for member in members if not member.is_dir()]
            if not files:
                raise IngestionError("empty_zip", "ZIP archive contains no files")
            if len(members) > SETTINGS.max_extracted_files:
                raise IngestionError("zip_file_count_exceeded", "ZIP archive contains too many entries", 413)

            total_size = 0
            seen_paths = set()
            for member in members:
                safe_path = _safe_member_path(member.filename)
                normalized_path = safe_path.as_posix().casefold()
                if normalized_path in seen_paths:
                    raise IngestionError("suspicious_zip", "ZIP archive contains duplicate file paths")
                seen_paths.add(normalized_path)
                if member.flag_bits & 0x1:
                    raise IngestionError("encrypted_zip", "Encrypted ZIP archives are not accepted")
                if member.is_dir() and (member.file_size or member.compress_size):
                    raise IngestionError("suspicious_zip", "ZIP archive contains an invalid directory entry")

                unix_mode = member.external_attr >> 16
                file_type = stat.S_IFMT(unix_mode)
                if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
                    raise IngestionError("suspicious_zip", "ZIP archive contains links or special files")
                if member.file_size > SETTINGS.max_extracted_file_bytes:
                    raise IngestionError("zip_file_size_exceeded", "ZIP archive contains a file larger than the configured limit", 413)
                total_size += member.file_size
                if total_size > SETTINGS.max_extracted_total_bytes:
                    raise IngestionError("zip_total_size_exceeded", "ZIP archive expands beyond the configured total-size limit", 413)
                if member.file_size and member.file_size / max(member.compress_size, 1) > SETTINGS.max_zip_compression_ratio:
                    raise IngestionError("suspicious_zip", "ZIP archive has a suspicious compression ratio")

            corrupt_member = archive.testzip()
            if corrupt_member is not None:
                raise IngestionError("corrupt_zip", "ZIP archive failed its integrity check")
    except IngestionError:
        raise
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise IngestionError("corrupt_zip", "ZIP archive is invalid, corrupted, or unsupported") from exc


def extract_zip_safely(zip_path: Path, destination: Path) -> None:
    inspect_zip_archive(zip_path)
    destination = destination.resolve()
    extracted_total = 0
    try:
        with zipfile.ZipFile(zip_path, "r") as archive:
            for member in archive.infolist():
                relative_path = _safe_member_path(member.filename)
                target = (destination / Path(*relative_path.parts)).resolve()
                try:
                    target.relative_to(destination)
                except ValueError as exc:
                    raise IngestionError("unsafe_zip_path", "ZIP archive contains a path that escapes the extraction directory") from exc
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue

                target.parent.mkdir(parents=True, exist_ok=True)
                extracted_file_size = 0
                with archive.open(member, "r") as source, target.open("xb") as output:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        extracted_file_size += len(chunk)
                        extracted_total += len(chunk)
                        if extracted_file_size > SETTINGS.max_extracted_file_bytes:
                            raise IngestionError("zip_file_size_exceeded", "Extracted file exceeds the configured limit", 413)
                        if extracted_total > SETTINGS.max_extracted_total_bytes:
                            raise IngestionError("zip_total_size_exceeded", "Extracted content exceeds the configured limit", 413)
                        output.write(chunk)
    except IngestionError:
        raise
    except (zipfile.BadZipFile, RuntimeError, NotImplementedError, OSError) as exc:
        raise IngestionError("corrupt_zip", "ZIP archive could not be extracted safely") from exc


def remove_temporary_directory(path: Optional[str]) -> None:
    if not path:
        return

    target = Path(path).resolve()
    temp_root = Path(tempfile.gettempdir()).resolve()
    try:
        target.relative_to(temp_root)
    except ValueError:
        return
    if target == temp_root or not target.name.startswith(("repo_zip_", "repo_clone_")):
        return

    def handle_remove_error(function, failed_path, _):
        os.chmod(failed_path, stat.S_IWRITE)
        function(failed_path)

    if target.is_dir():
        shutil.rmtree(target, onerror=handle_remove_error)
