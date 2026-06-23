"""Xuat toan bo database local (scores.db) ra seed.json de dua len Railway.
Chay:  .venv\\Scripts\\python export_seed.py
"""
import db
n, t = db.export_seed("seed.json")
print(f"Da xuat {n} anh va {t} thread vao seed.json")
print("Buoc tiep: commit seed.json roi push len Railway (xem README muc Phase 2).")
