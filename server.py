"""
VOZ Image Gallery + Swipe — backend
Scrape ảnh lớn (do user đăng) từ thread voz.vn / forum XenForo, lưu địa chỉ ảnh + điểm quẹt
vào DB để mở lại lần sau không cần quét lại; chỉ "Cập nhật" khi thread có trang mới.

Chạy local:  python server.py   →   http://127.0.0.1:8000
"""

import asyncio
import re
import time
import uuid
from urllib.parse import urlparse, urljoin, unquote

import httpx
from bs4 import BeautifulSoup
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse, RedirectResponse
from pydantic import BaseModel
import os
import io
import hashlib
import warnings

try:
    from PIL import Image  # tuy chon: dung de tao thumbnail
    warnings.filterwarnings("ignore", category=UserWarning, module="PIL")
except Exception:
    Image = None

import db

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
CACHE_DIR = os.path.join(BASE_DIR, "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

# Che do cong khai (Railway): chi gallery + quet (swipe) + vote, KHONG cho quet/them link
PUBLIC_MODE = os.environ.get("PUBLIC_MODE", "").lower() in ("1", "true", "yes", "on")
SEED_PATH = os.path.join(BASE_DIR, "seed.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

_BLOCK_SUBSTR = (
    "/avatars/", "gravatar.com", "statics.voz.tech", "/styles/",
    "voz-logo", "/reactions/", "/smilies/", "emoji", "/data/assets/",
    "/svg/", "sprite", "logo",
    # bo anh GIF (meme/sticker dong) - ke ca attachment dat ten dang "...-gif.NNN"
    ".gif", "-gif.",
    # host anh che / sticker / gif pho bien
    "giphy", "tenor", "gfycat", "imgflip", "/stickers/", "sticker", "anh.moe",
)
_IMG_EXT = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif")

app = FastAPI(title="VOZ Image Gallery")

JOBS: dict[str, dict] = {}


class ScrapeReq(BaseModel):
    url: str
    start: int | None = None
    end: int | None = None
    mode: str | None = None     # "update" = chỉ quét trang mới


class Vote(BaseModel):
    url: str
    dir: str
    thread: str | None = None
    author: str | None = None
    post: str | None = None
    w: int | None = None
    h: int | None = None


class ScoresReq(BaseModel):
    urls: list[str]


@app.on_event("startup")
async def _startup():
    db.init()
    if not PUBLIC_MODE:
        try:
            removed = db.cleanup()
            if removed:
                print(f"[cleanup] da xoa {removed} anh trung/loi")
        except Exception as ex:
            print("[cleanup] loi:", ex)
    if PUBLIC_MODE and os.path.exists(SEED_PATH):
        try:
            if db.count_images() == 0:
                n, t = db.import_seed(SEED_PATH)
                print(f"[seed] nap {n} anh, {t} thread tu seed.json")
        except Exception as ex:
            print("[seed] loi nap seed:", ex)


@app.get("/api/config")
async def api_config():
    return {"public": PUBLIC_MODE}


def normalize_thread(url: str) -> tuple[str, str]:
    url = url.split("#")[0].strip()
    p = urlparse(url)
    origin = f"{p.scheme}://{p.netloc}"
    path = p.path
    path = re.sub(r"/page-\d+/?$", "/", path)
    if not path.endswith("/"):
        path += "/"
    return origin, urljoin(origin, path)


def page_url(thread_base: str, n: int) -> str:
    if n <= 1:
        return thread_base
    return thread_base.rstrip("/") + f"/page-{n}"


def parse_title(html: str) -> str:
    m = re.search(r"<title>(.*?)</title>", html, re.S | re.I)
    if not m:
        return ""
    t = re.sub(r"\s+", " ", m.group(1)).strip()
    return re.split(r"\s*\|\s*", t)[0]


def is_wanted(u: str) -> bool:
    if not u:
        return False
    if u.startswith("data:"):
        return False
    low = u.lower()
    if any(b in low for b in _BLOCK_SUBSTR):
        return False
    if "/attachments/" in low:
        return True
    if low.startswith("http") and any(e in low.split("?")[0] for e in _IMG_EXT):
        return True
    return False


def _att_id(u: str):
    """Ma attachment voz (so cuoi). Dung de khu trung 1 anh co nhieu dang URL."""
    m = re.search(r"\.(\d+)/?$", u) or re.search(r"/attachments/(\d+)/?$", u)
    return m.group(1) if m else None


def _to_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def parse_total_pages(html: str) -> int:
    nums = [int(m) for m in re.findall(r"/page-(\d+)", html)]
    return max(nums) if nums else 1


def parse_images(html: str, base: str, page_no=None) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    seen: set[str] = set()

    articles = soup.select("article[data-author]") or [soup]
    for art in articles:
        author = art.get("data-author", "") if hasattr(art, "get") else ""
        permalink = ""
        a_perm = art.select_one('a[href*="/post-"]') if hasattr(art, "select_one") else None
        if a_perm and a_perm.get("href"):
            permalink = urljoin(base, a_perm["href"])

        # Quet TOAN BO anh trong bai (ke ca anh dinh kem ten img_2023..-jpg.NNN nam ngoai bbWrapper).
        # Loai avatar/reaction (qua is_wanted), anh trong quote va chu ky.
        imgs = art.select("img") if hasattr(art, "select") else []
        for img in imgs:
            if img.find_parent("blockquote") is not None:
                continue  # anh trong khung quote = comment, bo qua
            if img.find_parent(class_="message-signature") is not None:
                continue  # anh trong chu ky, bo qua
            if img.find_parent(class_="message-avatar") is not None:
                continue  # avatar, bo qua
            cand = (img.get("data-src") or img.get("data-url")
                    or img.get("data-original") or img.get("src") or "")
            cand = cand.strip()
            if cand.startswith("//"):
                cand = "https:" + cand
            elif cand and not cand.startswith("http") and not cand.startswith("data:"):
                cand = urljoin(base, cand)
            if not is_wanted(cand):
                continue
            w_px = _to_int(img.get("width"))
            h_px = _to_int(img.get("height"))
            if w_px and h_px and (w_px < 100 and h_px < 100):
                continue  # chi bo icon thuc su nho (ca 2 chieu < 100)
            if cand in seen:
                continue
            seen.add(cand)
            out.append({"url": cand, "w": w_px, "h": h_px,
                        "author": author, "post": permalink, "page": page_no})
    return out


async def fetch_page(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url, timeout=30, follow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        return None
    return None


async def run_job(job_id: str, url: str, start: int | None, end: int | None):
    job = JOBS[job_id]
    origin, base = normalize_thread(url)
    job["origin"] = origin
    job["thread_base"] = base
    headers = {"User-Agent": UA, "Referer": origin + "/",
               "Accept-Language": "vi,en;q=0.9"}
    seen_global: set[str] = set()

    async with httpx.AsyncClient(headers=headers, http2=False) as client:
        first = await fetch_page(client, page_url(base, start or 1))
        if first is None:
            job["status"] = "error"
            job["error"] = "Không tải được trang đầu. Kiểm tra lại link thread."
            return
        title = parse_title(first)
        job["title"] = title
        total = parse_total_pages(first)
        s = max(1, start or 1)
        e = min(end or total, total)
        if e < s:
            e = s
        job["total_pages"] = (e - s + 1)
        job["thread_total_pages"] = total

        sem = asyncio.Semaphore(10)

        def add_imgs(imgs):
            for im in imgs:
                k = _att_id(im["url"]) or im["url"]
                if k in seen_global:
                    continue
                seen_global.add(k)
                job["images"].append(im)

        async def handle(n: int, html: str | None = None):
            async with sem:
                if html is None:
                    html = await fetch_page(client, page_url(base, n))
                if html:
                    add_imgs(parse_images(html, origin, n))
                job["done_pages"] += 1

        tasks = []
        for n in range(s, e + 1):
            if n == (start or 1) and n == s:
                tasks.append(handle(n, first))
            else:
                tasks.append(handle(n))
        await asyncio.gather(*tasks)

    # lưu vào DB (giữ điểm cũ), cập nhật thông tin thread
    try:
        await asyncio.to_thread(db.save_images, base, job["images"])
        await asyncio.to_thread(db.upsert_thread, base, title, e, total)
    except Exception as ex:
        job["error"] = f"Lưu DB lỗi: {ex}"

    # tao truoc thumbnail (nen) -> gallery mo la co san, het o trong
    asyncio.create_task(prewarm([im["url"] for im in job["images"]], 440))

    job["status"] = "done"
    job["finished_at"] = time.time()


@app.post("/api/scrape")
async def api_scrape(req: ScrapeReq):
    if PUBLIC_MODE:
        raise HTTPException(403, "Chế độ công khai: không hỗ trợ quét. Hãy quét ở bản local.")
    start, end = req.start, req.end
    if (req.mode or "") == "update":
        _, base = normalize_thread(req.url)
        saved = await asyncio.to_thread(db.get_thread, base)
        start = saved["last_page"] if (saved and saved.get("last_page")) else 1
        end = None
    job_id = uuid.uuid4().hex[:12]
    JOBS[job_id] = {
        "status": "running", "images": [], "done_pages": 0,
        "total_pages": 0, "thread_total_pages": 0, "error": "",
        "started_at": time.time(), "url": req.url, "thread_base": "", "title": "",
    }
    asyncio.create_task(run_job(job_id, req.url, start, end))
    return {"job_id": job_id}


@app.get("/api/job/{job_id}")
async def api_job(job_id: str):
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(404, "job không tồn tại")
    return {
        "status": job["status"],
        "done_pages": job["done_pages"],
        "total_pages": job["total_pages"],
        "thread_total_pages": job["thread_total_pages"],
        "thread_base": job.get("thread_base", ""),
        "title": job.get("title", ""),
        "count": len(job["images"]),
        "images": job["images"],
        "error": job["error"],
    }


@app.post("/api/vote")
async def api_vote(v: Vote):
    like = 1 if v.dir == "like" else 0
    dislike = 1 if v.dir == "dislike" else 0
    if not like and not dislike:
        raise HTTPException(400, "dir phải là 'like' hoặc 'dislike'")
    await asyncio.to_thread(db.vote, v.url, v.thread or "", v.author or "",
                            v.post or "", v.w, v.h, like, dislike)
    return {"ok": True}


@app.post("/api/scores")
async def api_scores(r: ScoresReq):
    return await asyncio.to_thread(db.get_scores, r.urls)


@app.get("/api/gallery")
async def api_gallery(thread: str = Query(...)):
    _, base = normalize_thread(thread)
    imgs = await asyncio.to_thread(db.gallery_images, base)
    meta = await asyncio.to_thread(db.get_thread, base)
    return {"thread": base, "meta": meta, "count": len(imgs), "images": imgs}


@app.get("/api/threads")
async def api_threads():
    return await asyncio.to_thread(db.list_threads)


@app.get("/api/prewarm")
async def api_prewarm(thread: str = Query(...)):
    _, base = normalize_thread(thread)
    imgs = await asyncio.to_thread(db.gallery_images, base)
    asyncio.create_task(prewarm([im["url"] for im in imgs], 440))
    return {"ok": True, "count": len(imgs)}


@app.get("/api/top")
async def api_top(thread: str = "", limit: int = 500):
    return await asyncio.to_thread(db.top_images, thread, limit)


_DL_SEM = asyncio.Semaphore(8)   # gioi han tai dong thoi -> on dinh hon, do timeout


async def _download(target: str) -> bytes:
    p = urlparse(target)
    origin = f"{p.scheme}://{p.netloc}"
    headers = {"User-Agent": UA, "Referer": origin + "/",
               "Accept": "image/avif,image/webp,image/*,*/*;q=0.8"}
    last = None
    async with _DL_SEM:
        for _ in range(2):  # thu lai 1 lan
            try:
                async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=25) as client:
                    r = await client.get(target)
                if r.status_code == 200:
                    return r.content
                last = HTTPException(r.status_code, "anh tra ve loi")
            except Exception as ex:
                last = ex
    raise last or HTTPException(502, "khong tai duoc anh")


def _make_thumb(data: bytes, w: int, path: str):
    """Thu nhỏ ảnh xuống chiều rộng w, lưu JPEG vào path. Chạy trong thread."""
    im = Image.open(io.BytesIO(data))
    if im.mode in ("P", "LA", "RGBA"):
        im = im.convert("RGBA").convert("RGB")
    elif im.mode != "RGB":
        im = im.convert("RGB")
    if im.width > w:
        im = im.resize((w, max(1, round(im.height * w / im.width))))
    im.save(path, "JPEG", quality=80, optimize=True)


async def _ensure_thumb(target: str, w: int = 440) -> str | None:
    """Tao thumbnail (neu chua co) va tra ve duong dan cache. None neu that bai/khong co Pillow."""
    if Image is None:
        return None
    key = hashlib.sha1(f"{target}|{w}".encode()).hexdigest()
    path = os.path.join(CACHE_DIR, f"{key}.jpg")
    if os.path.exists(path):
        return path
    try:
        data = await _download(target)
        await asyncio.to_thread(_make_thumb, data, w, path)
        return path
    except Exception:
        return None


async def prewarm(urls, w: int = 440):
    """Tao truoc thumbnail cho toan bo anh sau khi quet -> gallery mo la co cache."""
    await asyncio.gather(*[_ensure_thumb(u, w) for u in urls], return_exceptions=True)


@app.get("/img")
async def proxy_img(u: str = Query(...), w: int | None = Query(None)):
    target = unquote(u)
    p = urlparse(target)
    if p.scheme not in ("http", "https"):
        raise HTTPException(400, "url không hợp lệ")

    # --- che do thumbnail (gallery) ---
    if w and Image is not None:
        w = max(80, min(int(w), 1600))
        path = await _ensure_thumb(target, w)
        if path:
            return FileResponse(path, media_type="image/jpeg",
                                headers={"Cache-Control": "public, max-age=604800"})
        raise HTTPException(502, "khong tao duoc thumbnail")

    # --- anh goc (khong co Pillow) ---
    try:
        data = await _download(target)
    except Exception:
        raise HTTPException(502, "khong tai duoc anh")
    return StreamingResponse(iter([data]), media_type="image/jpeg",
                             headers={"Cache-Control": "public, max-age=86400"})


@app.get("/", response_class=HTMLResponse)
async def index():
    with open(os.path.join(STATIC_DIR, "index.html"), encoding="utf-8") as f:
        return f.read()


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  VOZ Gallery + Swipe ->  http://127.0.0.1:{port}\n")
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
