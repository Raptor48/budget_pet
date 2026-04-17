from typing import List

from fastapi import APIRouter, HTTPException

from .models import TagCreate, TagOut, TagUpdate
from .repo import TagsRepository

router = APIRouter(prefix="/api/tags", tags=["tags"])


def _repo() -> TagsRepository:
    return TagsRepository()


@router.get("", response_model=List[TagOut])
async def list_tags():
    return await _repo().list_tags()


@router.post("", response_model=TagOut, status_code=201)
async def create_tag(body: TagCreate):
    return await _repo().create_tag(body.model_dump())


@router.get("/{tag_id}", response_model=TagOut)
async def get_tag(tag_id: int):
    tag = await _repo().get_tag(tag_id)
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    return tag


@router.patch("/{tag_id}", response_model=TagOut)
async def update_tag(tag_id: int, body: TagUpdate):
    updated = await _repo().update_tag(tag_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Tag not found")
    return updated


@router.delete("/{tag_id}", status_code=204)
async def delete_tag(tag_id: int):
    ok = await _repo().delete_tag(tag_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Tag not found")
