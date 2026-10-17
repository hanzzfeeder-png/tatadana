from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.security import get_current_user
from app.services.wallet_service import WalletService

router = APIRouter(prefix="/api/wallets", tags=["Wallets"])

class CreateWalletRequest(BaseModel):
    name: str
    type: str # 'cash', 'bank', 'ewallet', 'investment', 'other'
    initial_balance: float = 0.0
    icon: str = '👛'
    color: str = '#FF6B00'
    is_default: bool = False

class UpdateWalletRequest(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    icon: Optional[str] = None
    color: Optional[str] = None
    is_default: Optional[bool] = None

class TransferWalletRequest(BaseModel):
    source_wallet_id: str
    target_wallet_id: str
    amount: float
    note: Optional[str] = None

@router.get("")
def list_wallets(user: dict = Depends(get_current_user)):
    return {"success": True, "data": WalletService.get_wallets(user["id"])}

@router.post("")
def create_wallet(req: CreateWalletRequest, user: dict = Depends(get_current_user)):
    try:
        w = WalletService.create_wallet(
            user_id=user["id"],
            name=req.name,
            wallet_type=req.type,
            initial_balance=req.initial_balance,
            icon=req.icon,
            color=req.color,
            is_default=req.is_default
        )
        return {"success": True, "data": w}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.put("/{wallet_id}")
def update_wallet(wallet_id: str, req: UpdateWalletRequest, user: dict = Depends(get_current_user)):
    try:
        w = WalletService.update_wallet(
            wallet_id=wallet_id,
            user_id=user["id"],
            name=req.name,
            wallet_type=req.type,
            icon=req.icon,
            color=req.color,
            is_default=req.is_default
        )
        return {"success": True, "data": w}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.post("/transfer")
def transfer_between_wallets(req: TransferWalletRequest, user: dict = Depends(get_current_user)):
    try:
        res = WalletService.transfer(
            user_id=user["id"],
            source_wallet_id=req.source_wallet_id,
            target_wallet_id=req.target_wallet_id,
            amount=req.amount,
            note=req.note
        )
        return {"success": True, "data": res}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
