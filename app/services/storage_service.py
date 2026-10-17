import os
import uuid
from typing import Optional
import httpx
from app.config import settings

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
LOCAL_UPLOADS_DIR = os.path.join(BASE_DIR, "static", "uploads", "avatars")
os.makedirs(LOCAL_UPLOADS_DIR, exist_ok=True)

class StorageService:
    ALLOWED_IMAGE_TYPES = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp"
    }
    MAX_AVATAR_SIZE = 2 * 1024 * 1024  # 2MB

    @staticmethod
    def validate_avatar(file_bytes: bytes, content_type: str) -> str:
        """
        Validates avatar image MIME type and file size.
        Returns the appropriate file extension.
        """
        clean_type = content_type.lower().split(";")[0].strip()
        if clean_type not in StorageService.ALLOWED_IMAGE_TYPES:
            raise ValueError("Format file tidak didukung. Harap upload gambar berformat JPG, PNG, atau WebP.")

        if len(file_bytes) > StorageService.MAX_AVATAR_SIZE:
            raise ValueError("Ukuran file foto profil melebihi batas maksimum 2MB.")

        return StorageService.ALLOWED_IMAGE_TYPES[clean_type]

    @staticmethod
    def upload_avatar(user_id: str, file_bytes: bytes, content_type: str) -> str:
        """
        Uploads user avatar to Supabase Storage with graceful fallback to local storage.
        Returns the accessible URL (Supabase public URL or local static URL).
        """
        ext = StorageService.validate_avatar(file_bytes, content_type)
        file_name = f"avatar_{user_id}_{uuid.uuid4().hex[:6]}{ext}"

        # 1. Coba upload ke Supabase Storage jika kredensial tersedia
        supabase_url = (settings.SUPABASE_URL or "").strip().rstrip("/")
        service_key = (settings.SUPABASE_SERVICE_ROLE_KEY or "").strip()
        bucket = settings.SUPABASE_STORAGE_BUCKET or "tatadana-exports"

        if supabase_url and service_key:
            try:
                upload_endpoint = f"{supabase_url}/storage/v1/object/{bucket}/avatars/{file_name}"
                headers = {
                    "Authorization": f"Bearer {service_key}",
                    "Content-Type": content_type,
                    "x-upsert": "true"
                }
                res = httpx.post(upload_endpoint, content=file_bytes, headers=headers, timeout=10.0)
                if res.status_code in (200, 201):
                    return f"{supabase_url}/storage/v1/object/public/{bucket}/avatars/{file_name}"
                else:
                    print(f"[STORAGE WARN] Upload ke Supabase Storage merespon {res.status_code}: {res.text}. Menggunakan fallback lokal.")
            except Exception as e:
                print(f"[STORAGE WARN] Gagal menghubungi Supabase Storage: {e}. Menggunakan fallback lokal.")

        # 2. Fallback Lokal (lingkungan development / offline)
        local_path = os.path.join(LOCAL_UPLOADS_DIR, file_name)
        with open(local_path, "wb") as f:
            f.write(file_bytes)

        return f"/static/uploads/avatars/{file_name}"
