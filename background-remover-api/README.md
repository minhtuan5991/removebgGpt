# Background Remover API for Custom GPT

Backend API dùng FastAPI + Replicate `cjwbw/rembg` để xóa nền ảnh và trả về file PNG nền trong suốt.

## 1. Cấu trúc file

```text
background-remover-api/
├─ main.py
├─ requirements.txt
├─ .env.example
├─ render.yaml
├─ openapi-gpt-action.yaml
└─ output_files/
```

## 2. Chạy local để test

### Bước 1: Cài Python packages

```bash
pip install -r requirements.txt
```

### Bước 2: Tạo file `.env`

Copy file `.env.example` thành `.env`, sau đó điền token Replicate:

```env
REPLICATE_API_TOKEN=r8_your_replicate_token_here
PUBLIC_BASE_URL=http://localhost:8000
APP_API_KEY=change_this_to_a_secret_key
MAX_FILE_MB=15
FILE_TTL_HOURS=24
```

Nếu muốn test nhanh không cần API key, để:

```env
APP_API_KEY=
```

### Bước 3: Chạy API

```bash
uvicorn main:app --reload
```

Mở:

```text
http://localhost:8000
http://localhost:8000/docs
```

### Bước 4: Test bằng curl

Nếu không dùng API key:

```bash
curl -X POST "http://localhost:8000/remove-background" \
  -F "file=@test.jpg"
```

Nếu có dùng API key:

```bash
curl -X POST "http://localhost:8000/remove-background" \
  -H "x-api-key: change_this_to_a_secret_key" \
  -F "file=@test.jpg"
```

Kết quả trả về:

```json
{
  "success": true,
  "png_url": "http://localhost:8000/files/result.png",
  "filename": "result.png",
  "expires_after_hours": 24
}
```

## 3. Deploy lên Render

### Cách làm nhanh

1. Tạo GitHub repo mới.
2. Upload toàn bộ folder này lên GitHub.
3. Vào Render → New → Web Service.
4. Kết nối repo GitHub.
5. Cấu hình:

```text
Environment: Python
Build Command: pip install -r requirements.txt
Start Command: uvicorn main:app --host 0.0.0.0 --port $PORT
Plan: Free
```

6. Vào Environment Variables và thêm:

```text
REPLICATE_API_TOKEN = r8_your_replicate_token_here
PUBLIC_BASE_URL = https://your-render-app.onrender.com
APP_API_KEY = your_secret_api_key
MAX_FILE_MB = 15
FILE_TTL_HOURS = 24
```

7. Deploy.

Sau khi deploy xong, mở:

```text
https://your-render-app.onrender.com
https://your-render-app.onrender.com/docs
```

## 4. Kết nối với Custom GPT bằng Actions

1. Mở GPT Builder.
2. Vào GPT của bạn → Configure → Actions.
3. Create new action.
4. Mở file `openapi-gpt-action.yaml`.
5. Thay:

```text
https://YOUR-RENDER-APP.onrender.com
```

thành domain Render thật của bạn.

6. Dán schema vào GPT Action.
7. Nếu server có `APP_API_KEY`, thêm Authentication hoặc để schema dùng header `x-api-key`.

## 5. Instructions gợi ý cho GPT

```text
Bạn là GPT chuyên xóa nền ảnh.

Khi người dùng gửi ảnh và yêu cầu xóa nền:
- Gọi action removeBackground với ảnh người dùng gửi.
- Chỉ xóa nền, không thay đổi chủ thể chính, màu sắc, chữ, hình dạng hoặc chi tiết quan trọng.
- Sau khi action trả kết quả, gửi lại link PNG nền trong suốt cho người dùng.
- Nếu chưa có ảnh, yêu cầu người dùng tải ảnh lên.
- Trả lời ngắn gọn.
```

## 6. Lưu ý

- Render Free có thể sleep khi không dùng, lần gọi đầu có thể chậm.
- File PNG được lưu trong thư mục `output_files` và sẽ tự dọn file cũ theo `FILE_TTL_HOURS` khi có request mới.
- Không nên công khai API nếu không dùng `APP_API_KEY`.
- Replicate tính tiền theo lượt xử lý model.
