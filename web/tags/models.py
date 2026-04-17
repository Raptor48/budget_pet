from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TagOut(BaseModel):
    id: int
    name: str
    color: str = "#8b5cf6"
    created_at: datetime

    class Config:
        from_attributes = True


class TagCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    color: str = "#8b5cf6"


class TagUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=50)
    color: Optional[str] = None
