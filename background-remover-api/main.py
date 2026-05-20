import os
import uuid
import shutil
import tempfile
import time
from pathlib import Path

import requests
from dotenv import load_dotenv
from fastapi import FastAPI, UploadFile, File, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import replicate

load_dotenv()

# =========================
# ENV CONFIG
# =========================

REPLICATE_API_TOKEN = os.getenv("REPLICATE_API_TOKEN")
PUBLIC_BASE_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
APP_API_KEY = os.getenv("APP_API_KEY", "")
MAX_FILE_MB = int(os.getenv("MAX_FILE_MB", "15"))
FILE_TTL_HOURS = int(os.getenv("FILE_TTL_HOURS", "24"))

if not REPLICATE_API_TOKEN:
    raise RuntimeError("Missing REPLICATE_API_TOKEN environment variable")

if not PUBLIC_BASE_URL:
    raise RuntimeError("Missing PUBLIC_BASE_URL environment variable")

os.environ["REPLICATE_API_TOKEN"] = REPLICATE_API_TOKEN

# Replicate rembg model version
# Source: https://replicate.com/cjwbw/rembg/versions/fb8af171cfa1616ddcf1242c093f9c46bcada5ad4cf6f2fbe8b81b330ec5c003
REMBG_MODEL_VERSION = (
    "cjwbw/rembg:"
    "fb8af171cfa1616ddcf1242c093f9c46bcada5ad4cf6f2fbe8b81b330ec5c003"
)

OUTPUT_DIR = Path("output_files")
OUTPUT_DIR.mkdir(exist_ok=True)

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}

# =========================
# APP INIT
# =========================

app = FastAPI(
    title="Background Remover API",
    version="1.0.0",
    description="Remove image background with Replicate rembg and return transparent PNG URL.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/files", StaticFiles(directory=str(OUTPUT_DIR)), name="files")


# =========================
# HELPERS
# =========================

def check_api_key(x_api_key: str | None):
    """
    If APP_API_KEY is set, request must include matching x-api-key header.
    """
    if APP_API_KEY:
        if not x_api_key or x_api_key != APP_API_KEY:
            raise HTTPException(status_code=401, detail="Invalid or missing x-api-key")


def cleanup_old_files():
    """
    Delete old generated PNG files to prevent storage from growing forever.
    """
    now = time.time()
    ttl_seconds = FILE_TTL_HOURS * 3600

    for file_path in OUTPUT_DIR.glob("*"):
        try:
            if file_path.is_file():
                age = now - file_path.stat().st_mtime
                if age > ttl_seconds:
                    file_path.unlink()
        except Exception:
            pass


def validate_upload(file: UploadFile):
    filename = file.filename or ""
    ext = Path(filename).suffix.lower()

    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail="Unsupported file type. Please upload JPG, JPEG, PNG, or WEBP.",
        )

    return ext


def save_upload_to_temp(file: UploadFile, suffix: str) -> str:
    """
    Save uploaded image to a temporary file.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(file.file, tmp)
        temp_path = tmp.name

    file_size_mb = os.path.getsize(temp_path) / (1024 * 1024)
    if file_size_mb > MAX_FILE_MB:
        os.remove(temp_path)
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max file size is {MAX_FILE_MB}MB.",
        )

    return temp_path


def normalize_replicate_output(output):
    """
    Replicate output may be:
    - a string URL
    - a list containing URL
    - a FileOutput-like object
    """
    if isinstance(output, list):
        if not output:
            raise RuntimeError("Replicate returned empty output list")
        return str(output[0])

    return str(output)


def download_result_png(result_url: str) -> str:
    """
    Download PNG from Replicate result URL and save it locally.
    """
    response = requests.get(result_url, timeout=180)
    response.raise_for_status()

    output_filename = f"{uuid.uuid4()}.png"
    output_path = OUTPUT_DIR / output_filename

    with open(output_path, "wb") as f:
        f.write(response.content)

    return output_filename


# =========================
# ROUTES
# =========================

@app.get("/")
def root():
    return {
        "status": "ok",
        "message": "Background Remover API is running",
    }


@app.get("/health")
def health():
    return {
        "status": "healthy",
        "model": REMBG_MODEL_VERSION,
    }


@app.post("/remove-background")
async def remove_background(
    file: UploadFile = File(...),
    x_api_key: str | None = Header(default=None),
):
    """
    Upload an image, remove background, and return transparent PNG URL.
    """
    check_api_key(x_api_key)
    cleanup_old_files()

    suffix = validate_upload(file)
    temp_input_path = None

    try:
        temp_input_path = save_upload_to_temp(file, suffix)

        with open(temp_input_path, "rb") as image_file:
            output = replicate.run(
                REMBG_MODEL_VERSION,
                input={
                    "image": image_file,
                },
            )

        result_url = normalize_replicate_output(output)
        output_filename = download_result_png(result_url)

        png_url = f"{PUBLIC_BASE_URL}/files/{output_filename}"

        return {
            "success": True,
            "png_url": png_url,
            "filename": output_filename,
        }

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Background removal failed: {type(e).__name__}: {str(e)}",
        )

    finally:
        if temp_input_path and os.path.exists(temp_input_path):
            try:
                os.remove(temp_input_path)
            except Exception:
                pass
