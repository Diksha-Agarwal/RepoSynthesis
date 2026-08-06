from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path as FastAPIPath, UploadFile, status
from sqlalchemy.orm import Session

from api_schemas import DeleteResponse, ProjectCreateRequest, ProjectListResponse, ProjectResponse
from db import DATA_DIR, Project, get_db
from ingestion import (
    IngestionError,
    SETTINGS,
    inspect_zip_archive,
    require_public_github_repository,
)


router = APIRouter(prefix="/projects", tags=["projects"])
UPLOADS_DIR = SETTINGS.uploads_dir
PROJECTS_DIR = DATA_DIR / "projects"


def _raise_ingestion_error(exc: IngestionError):
    raise HTTPException(status_code=exc.status_code, detail=exc.as_detail()) from exc


def _store_uploaded_zip(file: UploadFile) -> Path:
    destination = UPLOADS_DIR / f"{uuid4().hex}.zip"
    uploaded_size = 0
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    try:
        with destination.open("xb") as output:
            while True:
                chunk = file.file.read(1024 * 1024)
                if not chunk:
                    break
                uploaded_size += len(chunk)
                if uploaded_size > SETTINGS.max_upload_zip_bytes:
                    raise IngestionError("upload_too_large", "Uploaded ZIP exceeds the configured size limit", 413)
                output.write(chunk)
        inspect_zip_archive(destination)
        return destination
    except Exception:
        destination.unlink(missing_ok=True)
        raise


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        github_url=project.github_url,
        uploaded_filename=Path(project.zip_filename).name if project.zip_filename else None,
        has_analysis=any(
            run.status == "completed" and run.result_record is not None
            for run in project.analysis_runs
        ),
    )


def get_project_or_404(
    project_id: int = FastAPIPath(..., gt=0, description="Numeric project ID"),
    db: Session = Depends(get_db),
) -> Project:
    project = db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    return project


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def create_github_project(payload: ProjectCreateRequest, db: Session = Depends(get_db)):
    """Create a project sourced from a public GitHub URL."""
    try:
        github_url = require_public_github_repository(str(payload.github_url))
    except IngestionError as exc:
        _raise_ingestion_error(exc)
    name = (payload.name or "").strip() or github_url.rstrip("/").split("/")[-1]
    project = Project(name=name, github_url=github_url)
    db.add(project)
    db.commit()
    db.refresh(project)
    return _project_response(project)


@router.post("/upload", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
def upload_project(
    name: Optional[str] = Form(default=None),
    github_url: Optional[str] = Form(default=None),
    file: Optional[UploadFile] = File(default=None),
    db: Session = Depends(get_db),
):
    """Create a project from a ZIP upload or a public GitHub URL.

    Use ``POST /projects`` for JSON GitHub submissions. This multipart route is
    retained for ZIP uploads and accepts no identity fields.
    """
    if not file and not github_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide a ZIP file or github_url")
    if file and github_url:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide either a ZIP file or github_url, not both")

    zip_filename = None
    project_name = name.strip() if name else None
    if file:
        if not file.filename or not file.filename.lower().endswith(".zip"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "invalid_file_type", "message": "Only .zip uploads are accepted"},
            )
        original_name = Path(file.filename).name
        try:
            zip_filename = _store_uploaded_zip(file)
        except IngestionError as exc:
            _raise_ingestion_error(exc)
        project_name = project_name or original_name
    else:
        try:
            github_url = require_public_github_repository(github_url)
        except IngestionError as exc:
            _raise_ingestion_error(exc)
        project_name = project_name or github_url.rstrip("/").split("/")[-1]

    project = Project(name=project_name, github_url=github_url, zip_filename=str(zip_filename) if zip_filename else None)
    try:
        db.add(project)
        db.commit()
        db.refresh(project)
    except Exception:
        db.rollback()
        if zip_filename:
            zip_filename.unlink(missing_ok=True)
        raise
    return _project_response(project)


@router.get("", response_model=ProjectListResponse)
def list_projects(db: Session = Depends(get_db)):
    projects = db.query(Project).order_by(Project.id.desc()).all()
    return ProjectListResponse(projects=[_project_response(project) for project in projects])


@router.get("/{project_id}", response_model=ProjectResponse)
def retrieve_project(project: Project = Depends(get_project_or_404)):
    return _project_response(project)


@router.delete("/{project_id}", response_model=DeleteResponse)
def delete_project(project: Project = Depends(get_project_or_404), db: Session = Depends(get_db)):
    project_id = project.id
    zip_path = Path(project.zip_filename) if project.zip_filename else None
    db.delete(project)
    db.commit()

    project_dir = PROJECTS_DIR / str(project_id)
    if project_dir.exists():
        import shutil
        shutil.rmtree(project_dir)
    if zip_path and zip_path.exists():
        try:
            zip_path.resolve().relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            pass
        else:
            zip_path.unlink()
    return DeleteResponse(status="deleted", project_id=project_id)
