from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Depends, BackgroundTasks
from sqlalchemy.orm import Session
from db import get_db, Project, User
import shutil
import requests
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "repo-processing"))
from pipeline import process_repository_for_graphflow

router = APIRouter()

def bg_task(project_id: str, zip_filename: str = None, github_url: str = None):
    try:
        file_path = zip_filename if zip_filename else github_url
        process_repository_for_graphflow(file_path, project_id=project_id)
        print(f"✅ Preprocessing complete for project {project_id}")
    except Exception as e:
        print(f"❌ Preprocessing failed for project {project_id}: {str(e)}")


@router.post("/projects/upload")
def upload_project(
    username: str = Form(...),
    name: str = Form(None),
    github_url: str = Form(None),
    file: UploadFile = File(None),
    db: Session = Depends(get_db)
):
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Validate input
    if not file and not github_url:
        raise HTTPException(status_code=400, detail="Either file or github_url must be provided")
    
    zip_filename = None
    project_name = name
    
    if file:
        os.makedirs("uploads", exist_ok=True)
        zip_filename = os.path.abspath(f"uploads/{db_user.username}_{file.filename}")
        with open(zip_filename, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        if not project_name:
            project_name = file.filename
    elif github_url:
        # Extract repo name from URL if name not provided
        if not project_name:
            project_name = github_url.rstrip('/').split('/')[-1]
    
    project = Project(
        user_id=db_user.id, 
        github_url=github_url, 
        zip_filename=zip_filename, 
        name=project_name
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    
    return {"message": "Project uploaded", "project_id": str(project.id)}

@router.get("/projects")
def list_projects(username: str, db: Session = Depends(get_db)):
    db_user = db.query(User).filter(User.username == username).first()
    if not db_user:
        raise HTTPException(status_code=403, detail="User not found")
    
    # Use absolute path
    base_dir = Path(__file__).parent / "data" / "projects"
    result = []
    for p in db_user.projects:
        analysis_file = base_dir / str(p.id) / "analysis_result.json"
        result.append({
            "id": p.id, 
            "name": p.name, 
            "github_url": p.github_url, 
            "zip_filename": p.zip_filename,
            "has_analysis": analysis_file.exists()
        })
    return result