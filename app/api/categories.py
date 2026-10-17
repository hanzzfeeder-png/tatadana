from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from typing import Optional
from app.security import get_current_user
from app.services.budget_service import BudgetService

router = APIRouter(prefix="/api/categories", tags=["Categories"])

class CreateCategoryRequest(BaseModel):
    name: str
    type: str # 'expense', 'income'
    icon: str = '🏷️'
    color: str = '#FF6B00'
    monthly_budget: float = 0.0

class UpdateCategoryRequest(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    monthly_budget: Optional[float] = None

@router.get("")
def list_categories(type: Optional[str] = None, user: dict = Depends(get_current_user)):
    return {"success": True, "data": BudgetService.get_categories(user["id"], type)}

@router.get("/budgets")
def list_category_budgets(user: dict = Depends(get_current_user)):
    return {"success": True, "data": BudgetService.get_budget_statuses(user["id"])}

@router.post("")
def create_category(req: CreateCategoryRequest, user: dict = Depends(get_current_user)):
    try:
        cat = BudgetService.create_category(
            user_id=user["id"],
            name=req.name,
            cat_type=req.type,
            icon=req.icon,
            color=req.color,
            monthly_budget=req.monthly_budget
        )
        return {"success": True, "data": cat}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{category_id}")
def update_category(category_id: str, req: UpdateCategoryRequest, user: dict = Depends(get_current_user)):
    try:
        cat = BudgetService.update_category(
            category_id=category_id,
            user_id=user["id"],
            name=req.name,
            icon=req.icon,
            color=req.color,
            monthly_budget=req.monthly_budget
        )
        return {"success": True, "data": cat}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
