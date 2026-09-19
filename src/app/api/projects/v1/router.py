from typing import List

# FastAPI router for Project endpoints (v1)
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_async_db
from .model import Project, ProjectCreate, ProjectUpdate
from . import service

router = APIRouter(prefix="/projects", tags=["projects"])

@router.get("/", response_model=List[Project])
async def read_projects(db: AsyncSession = Depends(get_async_db)) -> list[Project]:
    return await service.get_projects(db)  # type: ignore[return-value]

@router.get("/{project_id}", response_model=Project)
async def read_project(project_id: int, db: AsyncSession = Depends(get_async_db)) -> Project:
    project = await service.get_project(db, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project  # type: ignore[return-value]

@router.post("/", response_model=Project)
async def create_project(project: ProjectCreate, db: AsyncSession = Depends(get_async_db)) -> Project:
    return await service.create_project(db, project)  # type: ignore[return-value]

@router.put("/{project_id}", response_model=Project)
async def update_project(project_id: int, project: ProjectUpdate, db: AsyncSession = Depends(get_async_db)) -> Project:
    updated = await service.update_project(db, project_id, project)
    if not updated:
        raise HTTPException(status_code=404, detail="Project not found")
    return updated  # type: ignore[return-value]

@router.delete("/{project_id}")
async def delete_project(project_id: int, db: AsyncSession = Depends(get_async_db)) -> dict[str, bool]:
    await service.delete_project(db, project_id)
    return {"ok": True}
