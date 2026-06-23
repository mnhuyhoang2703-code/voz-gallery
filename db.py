"""
Lưu dữ liệu cho VOZ Gallery.
- Local: SQLite (file scores.db). Railway: Postgres khi có DATABASE_URL.
LƯU: địa chỉ ảnh + metadata + điểm quẹt + thông tin thread đã quét.
KHÔNG lưu file ảnh (ảnh load trực tiếp từ link voz).
"""
import os
import time
import json

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
IS_PG = DATABASE_URL.startswith("postgres")

if IS_PG:
    import psycopg2
    import psycopg2.pool
    _url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    _pool = psycopg2.pool.SimpleConnectionPool(1, 8, _url)
else:
    import sqlite3
    import threading
    _DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scores.db")
    _lock = threading.Lock()
    _conn = sqlite3.connect(_DB_PATH, check_same_thread=False)
    _conn.row_factory = sqlite3.Row


def _ph(sql: str) -> str:
    return sql.replace("?", "%s") if IS_PG else sql


class _Cur:
    def __enter__(self):
        if IS_PG:
            self.conn = _pool.getconn()
            self.cur = self.conn.cursor()
        else:
            _lock.acquire()
            self.conn = _conn
            self.cur = self.conn.cursor()
        return self.cur

    def __exit__(self, *exc):
        try:
            if exc[0] is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.cur.close()
            if IS_PG:
                _pool.putconn(self.conn)
            else:
                _lock.release()


def init():
    real = "DOUBLE PRECISION" if IS_PG else "REAL"
    with _Cur() as c:
        c.execute(f"""
        CREATE TABLE IF NOT EXISTS images(
            url      TEXT PRIMARY KEY,
            thread   TEXT,
            author   TEXT,
            post     TEXT,
            w        INTEGER,
            h        INTEGER,
            page     INTEGER,
            likes    INTEGER DEFAULT 0,
            dislikes INTEGER DEFAULT 0,
            updated  {real}
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_thread ON images(thread)")
        c.execute(f"""
        CREATE TABLE IF NOT EXISTS threads(
            thread      TEXT PRIMARY KEY,
            title       TEXT,
            last_page   INTEGER,
            total_pages INTEGER,
            updated     {real}
        )""")
    # them cot page neu DB cu thieu (transaction RIENG: PG se rollback ca block neu loi)
    try:
        with _Cur() as c2:
            c2.execute("ALTER TABLE images ADD COLUMN page INTEGER")
    except Exception:
        pass


# ---------- ghi ảnh đã quét ----------
def save_images(thread, imgs):
    """Lưu danh sách ảnh quét được. Giữ nguyên điểm like/dislike nếu ảnh đã tồn tại."""
    if not imgs:
        return
    sql = _ph("""
    INSERT INTO images(url,thread,author,post,w,h,page,likes,dislikes,updated)
    VALUES(?,?,?,?,?,?,?,0,0,?)
    ON CONFLICT(url) DO UPDATE SET
        thread = EXCLUDED.thread,
        author = COALESCE(EXCLUDED.author, images.author),
        post   = COALESCE(EXCLUDED.post,   images.post),
        w      = COALESCE(EXCLUDED.w,      images.w),
        h      = COALESCE(EXCLUDED.h,      images.h),
        page   = COALESCE(EXCLUDED.page,   images.page)
    """)
    now = time.time()
    rows = [(im["url"], thread, im.get("author"), im.get("post"),
             im.get("w"), im.get("h"), im.get("page"), now) for im in imgs]
    with _Cur() as c:
        c.executemany(sql, rows)


# ---------- vote ----------
def vote(url, thread, author, post, w, h, like, dislike):
    sql = _ph("""
    INSERT INTO images(url,thread,author,post,w,h,likes,dislikes,updated)
    VALUES(?,?,?,?,?,?,?,?,?)
    ON CONFLICT(url) DO UPDATE SET
        likes    = images.likes    + EXCLUDED.likes,
        dislikes = images.dislikes + EXCLUDED.dislikes,
        thread   = EXCLUDED.thread,
        author   = COALESCE(EXCLUDED.author, images.author),
        post     = COALESCE(EXCLUDED.post,   images.post),
        w        = COALESCE(EXCLUDED.w, images.w),
        h        = COALESCE(EXCLUDED.h, images.h),
        updated  = EXCLUDED.updated
    """)
    with _Cur() as c:
        c.execute(sql, (url, thread, author, post, w, h,
                        int(like), int(dislike), time.time()))


def get_scores(urls):
    if not urls:
        return {}
    out = {}
    CHUNK = 400
    for i in range(0, len(urls), CHUNK):
        part = urls[i:i + CHUNK]
        marks = ",".join("?" for _ in part)
        sql = _ph(f"SELECT url,likes,dislikes FROM images WHERE url IN ({marks})")
        with _Cur() as c:
            c.execute(sql, tuple(part))
            for row in c.fetchall():
                u, lk, dk = row[0], row[1], row[2]
                out[u] = {"likes": lk, "dislikes": dk, "score": lk - dk}
    return out


def _rows_to_imgs(rows):
    res = []
    for r in rows:
        res.append({"url": r[0], "thread": r[1], "author": r[2], "post": r[3],
                    "w": r[4], "h": r[5], "likes": r[6], "dislikes": r[7],
                    "score": r[6] - r[7]})
    return res


def gallery_images(thread, limit=100000):
    """Tất cả ảnh đã lưu của 1 thread, xếp theo điểm giảm dần."""
    sql = _ph("""SELECT url,thread,author,post,w,h,likes,dislikes
                 FROM images WHERE thread=?
                 ORDER BY (likes-dislikes) DESC, likes DESC LIMIT ?""")
    with _Cur() as c:
        c.execute(sql, (thread, limit))
        return _rows_to_imgs(c.fetchall())


def top_images(thread, limit=500):
    if thread:
        return gallery_images(thread, limit)
    sql = _ph("""SELECT url,thread,author,post,w,h,likes,dislikes
                 FROM images ORDER BY (likes-dislikes) DESC, likes DESC LIMIT ?""")
    with _Cur() as c:
        c.execute(sql, (limit,))
        return _rows_to_imgs(c.fetchall())


# ---------- thread meta ----------
def upsert_thread(thread, title, last_page, total_pages):
    sql = _ph("""
    INSERT INTO threads(thread,title,last_page,total_pages,updated)
    VALUES(?,?,?,?,?)
    ON CONFLICT(thread) DO UPDATE SET
        title       = EXCLUDED.title,
        last_page   = EXCLUDED.last_page,
        total_pages = EXCLUDED.total_pages,
        updated     = EXCLUDED.updated
    """)
    with _Cur() as c:
        c.execute(sql, (thread, title, last_page, total_pages, time.time()))


def get_thread(thread):
    sql = _ph("SELECT thread,title,last_page,total_pages,updated FROM threads WHERE thread=?")
    with _Cur() as c:
        c.execute(sql, (thread,))
        r = c.fetchone()
    if not r:
        return None
    return {"thread": r[0], "title": r[1], "last_page": r[2],
            "total_pages": r[3], "updated": r[4]}


def list_threads():
    sql = """SELECT t.thread,t.title,t.last_page,t.total_pages,t.updated,
                    (SELECT COUNT(*) FROM images i WHERE i.thread=t.thread) AS cnt
             FROM threads t ORDER BY t.updated DESC"""
    with _Cur() as c:
        c.execute(sql)
        rows = c.fetchall()
    return [{"thread": r[0], "title": r[1], "last_page": r[2],
             "total_pages": r[3], "updated": r[4], "count": r[5]} for r in rows]


# ---------- seed (xuat local -> nap Railway) ----------
def count_images():
    with _Cur() as c:
        c.execute("SELECT COUNT(*) FROM images")
        return c.fetchone()[0]


def export_seed(path):
    data = {"images": [], "threads": []}
    with _Cur() as c:
        c.execute("SELECT url,thread,author,post,w,h,page,likes,dislikes FROM images")
        for r in c.fetchall():
            data["images"].append({"url": r[0], "thread": r[1], "author": r[2], "post": r[3],
                                   "w": r[4], "h": r[5], "page": r[6], "likes": r[7], "dislikes": r[8]})
        c.execute("SELECT thread,title,last_page,total_pages FROM threads")
        for r in c.fetchall():
            data["threads"].append({"thread": r[0], "title": r[1], "last_page": r[2], "total_pages": r[3]})
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    return len(data["images"]), len(data["threads"])


def import_seed(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    now = time.time()
    isql = _ph("""INSERT INTO images(url,thread,author,post,w,h,page,likes,dislikes,updated)
                  VALUES(?,?,?,?,?,?,?,?,?,?)
                  ON CONFLICT(url) DO UPDATE SET
                    likes=EXCLUDED.likes, dislikes=EXCLUDED.dislikes,
                    thread=EXCLUDED.thread,
                    author=COALESCE(EXCLUDED.author, images.author),
                    post=COALESCE(EXCLUDED.post, images.post),
                    w=COALESCE(EXCLUDED.w, images.w),
                    h=COALESCE(EXCLUDED.h, images.h),
                    page=COALESCE(EXCLUDED.page, images.page)""")
    irows = [(im["url"], im.get("thread"), im.get("author"), im.get("post"), im.get("w"),
              im.get("h"), im.get("page"), im.get("likes", 0), im.get("dislikes", 0), now)
             for im in data.get("images", [])]
    with _Cur() as c:
        c.executemany(isql, irows)
    tsql = _ph("""INSERT INTO threads(thread,title,last_page,total_pages,updated)
                  VALUES(?,?,?,?,?)
                  ON CONFLICT(thread) DO UPDATE SET
                    title=EXCLUDED.title, last_page=EXCLUDED.last_page,
                    total_pages=EXCLUDED.total_pages""")
    trows = [(t["thread"], t.get("title"), t.get("last_page"), t.get("total_pages"), now)
             for t in data.get("threads", [])]
    with _Cur() as c:
        c.executemany(tsql, trows)
    return len(irows), len(trows)


def cleanup():
    """Don DB local: xoa anh host bi chan, gif, va link tran /attachments/NNN/ (trung ban -webp)."""
    total = 0
    blocked = ["anh.moe", "giphy", "tenor", "gfycat", "imgflip", "/stickers/",
               "/avatars/", "statics.voz.tech", "/reactions/", "/smilies/",
               "voz-logo", "/styles/", "gravatar.com"]
    with _Cur() as c:
        for b in blocked:
            c.execute(_ph("DELETE FROM images WHERE url LIKE ?"), (f"%{b}%",))
            total += max(c.rowcount or 0, 0)
        for g in [".gif", "-gif."]:
            c.execute(_ph("DELETE FROM images WHERE lower(url) LIKE ?"), (f"%{g}%",))
            total += max(c.rowcount or 0, 0)
        # link tran /attachments/NNN/ (khong co duoi -webp/-jpg...) = ban trung, hay loi
        c.execute("DELETE FROM images WHERE url GLOB '*/attachments/[0-9]*/' "
                  "AND url NOT LIKE '%-webp.%' AND url NOT LIKE '%-jpg.%' "
                  "AND url NOT LIKE '%-jpeg.%' AND url NOT LIKE '%-png.%' "
                  "AND url NOT LIKE '%-gif.%' AND url NOT LIKE '%-bmp.%' "
                  "AND url NOT LIKE '%-avif.%'")
        total += max(c.rowcount or 0, 0)
    return total
