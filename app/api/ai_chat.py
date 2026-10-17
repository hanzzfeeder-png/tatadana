from typing import Optional, List, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.security import get_current_user
from app.services.ai_service import AIService

router = APIRouter(prefix="/api/ai/chat", tags=["AI Chatbot"])

class SendMessageRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000, description="Pesan pertanyaan pengguna untuk Tata AI")

@router.get("/history")
def get_chat_history(
    limit: int = 50,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Mengambil riwayat percakapan pengguna dengan asisten finansial Tata AI.
    """
    messages = AIService.get_chat_history(user["id"], limit=limit)
    return {
        "success": True,
        "messages": messages
    }

@router.post("/send")
async def send_chat_message(
    payload: SendMessageRequest,
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Mengirim pesan percakapan ke Tata AI dan menerima jawaban berbasis konteks finansial pengguna.
    """
    text = payload.message.strip()
    if not text:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Pesan tidak boleh kosong.")

    result = await AIService.chat_with_assistant(user["id"], text)
    return result

@router.delete("/clear")
def clear_chat_history(
    user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Menghapus seluruh riwayat percakapan pengguna dengan Tata AI.
    """
    AIService.clear_chat_history(user["id"])
    return {
        "success": True,
        "message": "Riwayat percakapan berhasil dibersihkan"
    }
