from typing import List

from fastapi import APIRouter, HTTPException

from .models import CategoryCreate, CategoryOut, CategoryUpdate
from .repo import CategoriesRepository

router = APIRouter(prefix="/api/categories", tags=["categories"])


def _repo() -> CategoriesRepository:
    return CategoriesRepository()


@router.get("", response_model=List[CategoryOut])
async def list_categories():
    return await _repo().list_categories()


@router.post("", response_model=CategoryOut, status_code=201)
async def create_category(body: CategoryCreate):
    return await _repo().create_category(body.model_dump())


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(category_id: int):
    cat = await _repo().get_category(category_id)
    if not cat:
        raise HTTPException(status_code=404, detail="Category not found")
    return cat


@router.patch("/{category_id}", response_model=CategoryOut)
async def update_category(category_id: int, body: CategoryUpdate):
    updated = await _repo().update_category(category_id, body.model_dump(exclude_none=True))
    if not updated:
        raise HTTPException(status_code=404, detail="Category not found")
    return updated


@router.delete("/{category_id}", status_code=204)
async def delete_category(category_id: int):
    ok = await _repo().delete_category(category_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail="Category not found or cannot be deleted (Plaid-derived categories are kept)",
        )
