# VOZ Gallery + Swipe

Web app: quét ảnh các cô gái từ thread voz.vn, lưu vào database, xem dạng Gallery và quẹt kiểu Tinder để chấm điểm. Ảnh **không lưu file**, luôn load trực tiếp từ link voz (qua proxy + thumbnail); database chỉ lưu **địa chỉ ảnh + điểm**.

## Hai bản chạy

| | Local (máy bạn) | Public / Railway (cho mọi người) |
|---|---|---|
| Thêm link + Quét | ✅ | ❌ (khóa) |
| Gallery (xem ảnh) | ✅ | ✅ |
| Quẹt (Tinder) + chấm điểm | ✅ | ✅ |
| Database | SQLite (`scores.db`) | Postgres |

Ý tưởng: **quét ở local** để xây database → khi ưng → **xuất ra `seed.json`** → đẩy lên Railway, ở đó chỉ còn Gallery + Quẹt cho mọi người dùng chung.

## Chạy local (Windows)

Bấm đúp **`run.bat`** (cần Python 3.10+). Lần đầu tự cài thư viện (gồm Pillow để tạo thumbnail), rồi mở `http://127.0.0.1:8000`.

> ⚠️ Cửa sổ đen là **server** — để yên, đừng đóng, đừng click vào trong nó (click vào sẽ làm Windows tạm dừng = "đóng băng"; nếu lỡ, bấm phím Esc hoặc Enter trong cửa sổ để chạy tiếp).

Cách dùng: dán link thread → chọn khoảng trang (trống = toàn bộ) → **Quét**. Quét xong tự lưu; lần sau chọn ở ô **"Thread đã lưu"** để xem ngay. Thread có trang mới thì bấm **↻ Cập nhật trang mới**.

## Lọc ảnh (chỉ lấy ảnh gái)

Giữ ảnh lớn trong bài (attachments + ảnh nhúng ngoài). Bỏ: avatar, icon reaction, logo, smilies, **GIF** (kể cả gif đính kèm), host ảnh chế (giphy/tenor/gfycat/imgflip), và **ảnh nằm trong khung trích dẫn/quote** (meme/icon trong comment).

## Hiệu năng

- Gallery hiển thị **thumbnail ~440px** (server thu nhỏ + cache đĩa `cache/`) → nhẹ, không lag; render theo lô khi cuộn.
- Tinder và xem-lớn dùng **ảnh gốc**.
- Trong lúc quét, gallery KHÔNG tải thumbnail (để không giành băng thông) — chỉ hiện tiến trình, render đầy đủ khi xong.

## Phase 2 — Đưa lên Railway (public, sau khi local quét đủ)

1. **Quét đủ ở local** rồi kiểm tra Gallery ưng ý.
2. Xuất database ra file seed:
   ```bat
   .venv\Scripts\python export_seed.py
   ```
   → tạo `seed.json` (toàn bộ ảnh + điểm + thread).
3. Push code **kèm `seed.json`** lên GitHub. (Lưu ý: `.gitignore` đang bỏ qua `scores.db`, `cache/`, `.venv/` — nhưng **seed.json vẫn được commit**.)
4. Trên Railway: **New Project → Deploy from GitHub** → chọn repo.
5. Add plugin **PostgreSQL** (Railway tự tạo biến `DATABASE_URL`).
6. Thêm biến môi trường **`PUBLIC_MODE=1`** (Variables).
7. Railway build theo `requirements-railway.txt`? → đặt biến `NIXPACKS_...` không cần; mặc định Railway đọc `requirements.txt`. Để có psycopg2 + Pillow trên Railway, đổi tên hoặc trỏ build dùng `requirements-railway.txt` (xem ghi chú dưới).
8. Khi khởi động, nếu DB rỗng, app tự **nạp `seed.json`** vào Postgres. `PUBLIC_MODE=1` sẽ **ẩn phần Quét/Thêm link**, chỉ còn Gallery + Quẹt. Điểm quẹt của mọi người cộng dồn vào Postgres (bền qua mỗi lần deploy).

> Ghi chú deps trên Railway: bản public cần `psycopg2-binary` và `pillow`. Cách đơn giản: trước khi push, thêm 2 dòng đó vào `requirements.txt` (Railway sẽ cài). Local không bắt buộc có chúng (psycopg2 chỉ dùng khi có `DATABASE_URL`; pillow chỉ để thumbnail).

## Cấu trúc

| File | Vai trò |
|------|---------|
| `server.py` | FastAPI: scrape + proxy/thumbnail + API gallery/threads/vote/scores/config |
| `db.py` | SQLite (local) / Postgres (Railway) + export/import seed |
| `static/index.html` | Giao diện (gallery + swipe + lightbox); tự ẩn phần quét khi public |
| `export_seed.py` | Xuất `scores.db` → `seed.json` |
| `run.bat`, `requirements.txt` | Chạy & cài local |
| `Procfile`, `runtime.txt`, `requirements-railway.txt` | Cấu hình Railway |

## API

- `GET  /api/config` → `{public}` (ẩn quét khi true)
- `POST /api/scrape` (khóa khi public) · `GET /api/job/{id}`
- `GET  /api/gallery?thread=` · `GET /api/threads`
- `POST /api/vote` · `POST /api/scores` · `GET /api/top`
- `GET  /img?u=<url>[&w=440]` → ảnh gốc / thumbnail
