import os
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import init_db
from app.security import get_current_user_optional, get_current_user, require_admin

# API Routers
from app.api.auth import router as auth_router
from app.api.transactions import router as transactions_router
from app.api.wallets import router as wallets_router
from app.api.categories import router as categories_router
from app.api.reports import router as reports_router
from app.api.telegram import router as telegram_router
from app.api.payments import router as payments_router
from app.api.admin import router as admin_router
from app.api.settings import router as settings_router

# Initialize FastAPI App
app = FastAPI(
    title=settings.APP_NAME,
    description="SaaS TataDana — Catat Keuangan Semudah Chat dari Telegram",
    version="1.0.0"
)

# Initialize Database Schema & Seed Data
init_db()

# Paths
BASE_DIR = os.path.dirname(os.path.dirname(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")

# Mount Static Files
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

# Templates
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Register API Routers
app.include_router(auth_router)
app.include_router(transactions_router)
app.include_router(wallets_router)
app.include_router(categories_router)
app.include_router(reports_router)
app.include_router(telegram_router)
app.include_router(payments_router)
app.include_router(admin_router)
app.include_router(settings_router)

# =============================================================================
# WEB PAGE ROUTES (FRONTEND RENDERING)
# =============================================================================

@app.get("/", response_class=HTMLResponse)
def page_landing(request: Request):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request=request, name="landing.html", context={"user": None})

@app.get("/login", response_class=HTMLResponse)
def page_login(request: Request):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request=request, name="auth/login.html", context={})

@app.get("/register", response_class=HTMLResponse)
def page_register(request: Request):
    user = get_current_user_optional(request)
    if user:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse(request=request, name="auth/register.html", context={})

@app.get("/privacy", response_class=HTMLResponse)
def page_privacy(request: Request):
    return templates.TemplateResponse(request=request, name="legal/privacy.html", context={})

@app.get("/terms", response_class=HTMLResponse)
def page_terms(request: Request):
    return templates.TemplateResponse(request=request, name="legal/terms.html", context={})

# Dashboard Pages
@app.get("/dashboard", response_class=HTMLResponse)
def page_dashboard_beranda(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="dashboard/beranda.html", context={
        "user": user,
        "active_page": "beranda"
    })

@app.get("/dashboard/transaksi", response_class=HTMLResponse)
def page_dashboard_transaksi(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="dashboard/transaksi.html", context={
        "user": user,
        "active_page": "transaksi"
    })

@app.get("/dashboard/laporan", response_class=HTMLResponse)
def page_dashboard_laporan(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="dashboard/laporan.html", context={
        "user": user,
        "active_page": "laporan"
    })

@app.get("/dashboard/budget", response_class=HTMLResponse)
def page_dashboard_budget(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="dashboard/budget.html", context={
        "user": user,
        "active_page": "budget"
    })

@app.get("/dashboard/wallet", response_class=HTMLResponse)
def page_dashboard_wallet(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="dashboard/wallet.html", context={
        "user": user,
        "active_page": "wallet"
    })

@app.get("/dashboard/settings", response_class=HTMLResponse)
def page_dashboard_settings(request: Request):
    user = get_current_user_optional(request)
    if not user:
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="dashboard/settings.html", context={
        "user": user,
        "active_page": "settings"
    })

def check_admin_web_access(user: Optional[dict]) -> bool:
    if not user:
        return False
    return (user.get("role") in ("superadmin", "admin")) or bool(user.get("is_admin"))

# Admin Pages
@app.get("/admin", response_class=HTMLResponse)
def page_admin_index(request: Request):
    user = get_current_user_optional(request)
    if not check_admin_web_access(user):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="admin/index.html", context={
        "user": user,
        "active_admin_page": "overview"
    })

@app.get("/admin/ai-providers", response_class=HTMLResponse)
def page_admin_ai_providers(request: Request):
    user = get_current_user_optional(request)
    if not check_admin_web_access(user):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="admin/ai_providers.html", context={
        "user": user,
        "active_admin_page": "ai_providers"
    })

@app.get("/admin/users", response_class=HTMLResponse)
def page_admin_users(request: Request):
    user = get_current_user_optional(request)
    if not check_admin_web_access(user):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="admin/users.html", context={
        "user": user,
        "active_admin_page": "users"
    })

@app.get("/admin/payments", response_class=HTMLResponse)
def page_admin_payments(request: Request):
    user = get_current_user_optional(request)
    if not check_admin_web_access(user):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="admin/payments.html", context={
        "user": user,
        "active_admin_page": "payments"
    })

@app.get("/admin/ai-logs", response_class=HTMLResponse)
def page_admin_ai_logs(request: Request):
    user = get_current_user_optional(request)
    if not check_admin_web_access(user):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="admin/ai_logs.html", context={
        "user": user,
        "active_admin_page": "ai_logs"
    })

@app.get("/admin/audit-logs", response_class=HTMLResponse)
def page_admin_audit_logs(request: Request):
    user = get_current_user_optional(request)
    if not check_admin_web_access(user):
        return RedirectResponse(url="/login")
    return templates.TemplateResponse(request=request, name="admin/audit_logs.html", context={
        "user": user,
        "active_admin_page": "audit_logs"
    })

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
