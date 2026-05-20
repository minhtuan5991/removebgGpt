import os
import uuid
import shutil
import tempfile
import time
from pathlib import Path
from typing import Optional

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import replicate

load_dotenv()

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
APP_API_KEY = os.getenv("APP_API_KEY", "")
OUTPUT_DIR = Path(os.getenv("OUTPUT_DIR", "output_files"))
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "15"))
FILE_TTL_HOURS = int(os.getenv("FILE_TTL_HOURS", "24"))

if not REPLICATE_API_TOKEN:
    raise RuntimeError("Missing REPLICATE_API_TOKEN. Please set it in Render Environment Variables or .env")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Background Remover API",
    description="Remove image background with Replicate rembg and return transparent PNG URL.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")


def verify_api_key(x_api_key: Optional[str] = Header(default=None)):
    """Optional API key protection. If APP_API_KEY is empty, the API is open."""
    if APP_API_KEY and x_api_key != APP_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing x-api-key")


def cleanup_old_files():
    """Delete generated files older than FILE_TTL_HOURS."""
    now = time.time()
    ttl_seconds = FILE_TTL_HOURS * 3600
    for file_path in OUTPUT_DIR.glob("*.png"):
        try:
            if now - file_path.stat().st_mtime > ttl_seconds:
                file_path.unlink(missing_ok=True)
        except Exception:
            pass


@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Background Remover API is running",
        "docs": f"{PUBLIC_BASE_URL}/docs",
    }


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.post("/remove-background", dependencies=[Depends(verify_api_key)])
async def remove_background(file: UploadFile = File(...)):
    cleanup_old_files()

    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/webp"}
    if file.content_type not in allowed_types:
        raise HTTPException(status_code=400, detail="Only PNG, JPG, JPEG, and WEBP images are supported")

    temp_input_path = None

    try:
        suffix = Path(file.filename or "image.png").suffix.lower()
        if suffix not in [".png", ".jpg", ".jpeg", ".webp"]:
            suffix = ".png"

        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            size = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_FILE_MB * 1024 * 1024:
                    raise HTTPException(status_code=413, detail=f"File too large. Max size is {MAX_FILE_MB}MB")
                tmp.write(chunk)
            temp_input_path = tmp.name

        with open(temp_input_path, "rb") as image_file:
            output = replicate.run(
                "cjwbw/rembg:fb8af171cfa1610a9b2044da04e50135cc65450680a7d5344f987fb5bf3db574",
                input={"image": image_file}
            )

        if isinstance(output, list):
            result_url = str(output[0])
        else:
            result_url = str(output)

        result_response = requests.get(result_url, timeout=180)
        result_response.raise_for_status()

        output_filename = f"{uuid.uuid4()}.png"
        output_path = OUTPUT_DIR / output_filename
        output_path.write_bytes(result_response.content)

        png_url = f"{PUBLIC_BASE_URL}/files/{output_filename}"

        return {
            "success": True,
            "png_url": png_url,
            "filename": output_filename,
            "expires_after_hours": FILE_TTL_HOURS,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Background removal failed: {str(e)}")
    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            os.remove(temp_input_path)
