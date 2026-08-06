import os
import subprocess
import tempfile
from pathlib import Path

import nbformat

from ingestion import (
    IngestionError,
    SETTINGS,
    extract_zip_safely,
    remove_temporary_directory,
    require_public_github_repository,
    resolve_uploaded_zip,
)
from models import Document


class RepoLoader:
    @staticmethod
    def load_zip(zip_file_path: str) -> str:
        zip_path = resolve_uploaded_zip(zip_file_path)
        temp_dir = tempfile.mkdtemp(prefix="repo_zip_")
        try:
            extract_zip_safely(zip_path, Path(temp_dir))
            return temp_dir
        except Exception:
            remove_temporary_directory(temp_dir)
            raise

    @staticmethod
    def load_github(url: str) -> str:
        """Validate and shallow-clone a public GitHub repository."""
        canonical_url = require_public_github_repository(url)
        temp_dir = tempfile.mkdtemp(prefix="repo_clone_")
        command = [
            "git",
            "-c",
            "protocol.file.allow=never",
            "clone",
            "--depth",
            "1",
            "--single-branch",
            "--no-tags",
            canonical_url,
            temp_dir,
        ]
        environment = os.environ.copy()
        environment["GIT_TERMINAL_PROMPT"] = "0"
        clone_completed = False
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=SETTINGS.repository_clone_timeout_seconds,
                check=False,
                env=environment,
            )
            if result.returncode != 0:
                raise IngestionError("github_clone_failed", "Failed to clone the public GitHub repository")
            clone_completed = True
            return temp_dir
        except subprocess.TimeoutExpired as exc:
            raise IngestionError(
                "github_clone_timeout",
                "GitHub repository clone exceeded the configured timeout",
                504,
            ) from exc
        except OSError as exc:
            raise IngestionError("git_unavailable", "Git is unavailable on the backend server", 500) from exc
        except Exception:
            raise
        finally:
            if not clone_completed:
                remove_temporary_directory(temp_dir)

    @staticmethod
    def load_repo(input_value: str) -> str:
        if str(input_value).lower().endswith(".zip"):
            return RepoLoader.load_zip(input_value)
        if str(input_value).startswith("https://"):
            return RepoLoader.load_github(input_value)
        raise IngestionError("invalid_repository_source", "Repository source must be a server upload or public GitHub URL")

    @staticmethod
    def cleanup(repo_path: str) -> None:
        remove_temporary_directory(repo_path)

    @staticmethod
    def load_documents(repo_path: str) -> list[Document]:
        repo_root = Path(repo_path).resolve()
        skip_dirs = {"node_modules", "__pycache__", ".git", ".venv", "venv", ".tox", "dist", "build"}
        skip_extensions = {
            ".pyc", ".pyo", ".exe", ".dll", ".so", ".o", ".a",
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg",
            ".woff", ".woff2", ".ttf", ".eot",
            ".zip", ".tar", ".gz", ".lock",
        }

        def is_valid_file(file_path):
            candidate = Path(file_path)
            if candidate.is_symlink():
                return False
            try:
                candidate.resolve().relative_to(repo_root)
            except ValueError:
                return False
            parts = file_path.replace("\\", "/").split("/")
            for part in parts:
                if part.startswith(".") or part in skip_dirs:
                    return False
            filename = os.path.basename(file_path)
            if filename.startswith(".env"):
                return False
            extension = Path(file_path).suffix.lower()
            return extension not in skip_extensions and os.path.isfile(file_path)

        def notebook_to_code(file_path: str):
            try:
                with open(file_path, "r", encoding="utf-8") as source:
                    notebook = nbformat.read(source, as_version=4)
                return "\n\n".join(cell.source for cell in notebook.cells if cell.cell_type == "code")
            except Exception as exc:
                print(f"Failed to read notebook {file_path}: {exc}")
                return ""

        def read_file_safe(file_path: str) -> str:
            for encoding in ("utf-8", "latin-1"):
                try:
                    with open(file_path, "r", encoding=encoding) as source:
                        return source.read()
                except (UnicodeDecodeError, ValueError):
                    continue
            return ""

        documents = []
        try:
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [
                    directory
                    for directory in dirs
                    if directory not in skip_dirs
                    and not directory.startswith(".")
                    and not (Path(root) / directory).is_symlink()
                ]
                for filename in files:
                    file_path = os.path.join(root, filename)
                    if not is_valid_file(file_path):
                        continue
                    if Path(file_path).suffix.lower() == ".ipynb":
                        content = notebook_to_code(file_path)
                    else:
                        content = read_file_safe(file_path)
                    if content.strip():
                        relative_path = Path(file_path).resolve().relative_to(repo_root).as_posix()
                        documents.append(
                            Document(
                                page_content=content,
                                metadata={"source": relative_path, "path": relative_path},
                            )
                        )

            print(f"Loaded {len(documents)} documents from {repo_path}")
            return documents
        finally:
            RepoLoader.cleanup(repo_path)
