from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from db import User, Project, get_db
from pathlib import Path
import json

router = APIRouter(prefix="/admin")
# Use absolute path based on file location
BASE_DATA_DIR = Path(__file__).parent / "data" / "projects"

@router.get("/users")
def get_all_users(admin_username: str, db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.username == admin_username).first()
    if not admin or not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    
    users = db.query(User).all()
    return [{"id": u.id, "username": u.username, "is_admin": bool(u.is_admin)} for u in users]

@router.get("/projects")
def get_all_projects(admin_username: str, db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.username == admin_username).first()
    if not admin or not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    
    projects = db.query(Project).all()
    result = []
    for p in projects:
        username = db.query(User).filter(User.id == p.user_id).first().username
        project_dir = BASE_DATA_DIR / str(p.id)
        analysis_file = project_dir / "analysis_result.json"
        has_analysis = analysis_file.exists()
        
        result.append({
            "id": p.id, 
            "name": p.name, 
            "user_id": p.user_id,
            "username": username,
            "zip_filename": p.zip_filename,
            "has_analysis": has_analysis
        })
    return result

@router.get("/projects/{project_id}/analysis")
def get_project_analysis(project_id: str, admin_username: str, db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.username == admin_username).first()
    if not admin or not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    
    analysis_file = BASE_DATA_DIR / project_id / "analysis_result.json"
    if not analysis_file.exists():
        raise HTTPException(status_code=404, detail="No analysis found")
    
    with open(analysis_file) as f:
        return json.load(f)

@router.get("/projects/{project_id}/download")
def download_project_zip(project_id: str, admin_username: str, db: Session = Depends(get_db)):
    admin = db.query(User).filter(User.username == admin_username).first()
    if not admin or not admin.is_admin:
        raise HTTPException(status_code=403, detail="Admin only")
    
    project = db.query(Project).filter(Project.id == int(project_id)).first()
    if not project or not project.zip_filename:
        raise HTTPException(status_code=404, detail="ZIP file not found")
    
    zip_path = Path(project.zip_filename)
    if not zip_path.exists():
        raise HTTPException(status_code=404, detail="ZIP file not found on disk")
    
    return FileResponse(zip_path, filename=zip_path.name)
