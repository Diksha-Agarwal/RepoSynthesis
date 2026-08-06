import shutil
from pathlib import Path
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path as FastAPIPath, UploadFile, status
from sqlalchemy.orm import Session

from api_schemas import DeleteResponse, ProjectCreateRequest, ProjectListResponse, ProjectResponse
from db import DATA_DIR, Project, get_db


router = APIRouter(prefix="/projects", tags=["projects"])
UPLOADS_DIR = DATA_DIR / "uploads"
PROJECTS_DIR = DATA_DIR / "projects"


def _project_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        github_url=project.github_url,
        uploaded_filename=Path(project.zip_filename).name if project.zip_filename else None,
        has_analysis=(PROJECTS_DIR / str(project.id) / "analysis_result.json").exists(),
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
    github_url = str(payload.github_url)
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Uploaded file must be a ZIP archive")
        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        safe_filename = Path(file.filename).name
        zip_filename = UPLOADS_DIR / f"{uuid4().hex}_{safe_filename}"
        with zip_filename.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        project_name = project_name or safe_filename
    else:
        github_url = github_url.strip()
        if not github_url.startswith(("https://", "http://")):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="github_url must be an HTTP(S) URL")
        project_name = project_name or github_url.rstrip("/").split("/")[-1]

    project = Project(name=project_name, github_url=github_url, zip_filename=str(zip_filename) if zip_filename else None)
    db.add(project)
    db.commit()
    db.refresh(project)
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
        shutil.rmtree(project_dir)
    if zip_path and zip_path.exists():
        try:
            zip_path.resolve().relative_to(UPLOADS_DIR.resolve())
        except ValueError:
            pass
        else:
            zip_path.unlink()
    return DeleteResponse(status="deleted", project_id=project_id)
