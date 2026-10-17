import uvicorn
from app.config import settings

if __name__ == "__main__":
    print(f"=======================================================")
    print(f"[INFO] Memulai TataDana Production Server...")
    print(f"   URL: http://localhost:{settings.PORT}")
    print(f"   Timezone: {settings.APP_TIMEZONE} (WIB)")
    print(f"   Akun Demo: demo@tatadana.id / demo123456")
    print(f"   Akun Admin: admin@tatadana.id / admin123456")
    print(f"=======================================================")
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=settings.DEBUG)
