# Đưa bản công khai lên Railway — ngamgaixinhvoz

Bản công khai = **chỉ Gallery + Quẹt + chấm điểm** (tự khóa phần Quét nhờ `PUBLIC_MODE=1`).
Ảnh vẫn load thẳng từ voz trong trình duyệt khách; Railway chỉ lưu **điểm + danh sách ảnh** (Postgres).

> Vài bước phải đăng nhập tài khoản của anh (GitHub, Railway) — mình không làm hộ được, anh tự bấm theo đúng thứ tự dưới.

## Bước 1 — Tạo file dữ liệu seed.json (trên máy anh)
Bấm đúp **`make_seed.bat`** (hoặc chạy `.venv\Scripts\python export_seed.py`).
→ Tạo `seed.json` chứa toàn bộ 16.861 ảnh + điểm. Railway sẽ nạp file này.

## Bước 2 — Đẩy code lên GitHub
Mở **Git CMD** (hoặc Command Prompt) trong thư mục `voz-gallery`, chạy:

```bat
git init
git add .
git commit -m "VOZ gallery public"
git branch -M main
git remote add origin https://github.com/<TEN_GITHUB>/voz-gallery.git
git push -u origin main
```

(Trước đó tạo 1 repo trống tên `voz-gallery` trên github.com. `seed.json` sẽ được đẩy lên; `scores.db`, `cache/`, `.venv/` đã bị bỏ qua.)

## Bước 3 — Tạo project trên Railway
1. Vào **railway.app** → đăng nhập (bằng GitHub).
2. **New Project → Deploy from GitHub repo** → chọn repo `voz-gallery`.
3. Railway tự build theo `requirements.txt` + `Procfile`.

## Bước 4 — Thêm PostgreSQL (để lưu điểm bền)
- Trong project: **New → Database → Add PostgreSQL**.
- Railway tự tạo biến `DATABASE_URL` cho app (không cần làm gì thêm).

## Bước 5 — Bật chế độ công khai
- Vào service (app) → tab **Variables** → **New Variable**:
  - `PUBLIC_MODE` = `1`
- App sẽ tự redeploy. Khi khởi động, nếu DB trống nó **tự nạp seed.json** vào Postgres (16.861 ảnh) và **ẩn phần Quét**.

## Bước 6 — Đặt tên miền ngamgaixinhvoz
- Vào service → **Settings → Networking → Public Networking → Generate Domain**.
- Sửa phần đầu thành **`ngamgaixinhvoz`** → địa chỉ web sẽ là:
  **https://ngamgaixinhvoz.up.railway.app**
  (nếu tên đã có người dùng, Railway báo trùng — chọn tên khác.)

## Xong
Mở `https://ngamgaixinhvoz.up.railway.app` → mọi người vào xem Gallery (ảnh nhiều tim lên đầu) và Quẹt để chấm điểm. Điểm cộng dồn chung, bền qua mỗi lần deploy.

## Lưu ý
- Ảnh load trực tiếp từ voz trong trình duyệt khách. Thread này công khai (khách xem được) nên OK; nếu voz đổi chính sách hotlink thì có thể lỗi một số ảnh.
- Muốn cập nhật ảnh mới sau này: ở **local** bấm "Cập nhật trang mới" → chạy lại `make_seed.bat` → `git add . && git commit -m "update" && git push`. Railway tự deploy lại. (DB Postgres giữ nguyên điểm; chỉ thêm ảnh mới khi bạn thêm cơ chế merge — hiện seed chỉ nạp khi DB trống.)
