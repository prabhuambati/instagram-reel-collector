from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "collection.db"
MEDIA_DIR = DATA_DIR / "media"
EXPORT_DIR = DATA_DIR / "exports"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slug(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9_-]+", "_", value or "unknown").strip("_")
    return value[:80] or "unknown"


@dataclass
class ReelRecord:
    reel_url: str
    username: str = ""
    profile_url: str = ""
    profile_photo_url: str = ""
    instagram_id: str = ""
    caption: str = ""
    source_kind: str = "manual"
    source_query: str = ""
    video_url: str = ""
    local_video_path: str = ""
    mp3_path: str = ""
    video_sha256: str = ""
    audio_sha256: str = ""
    song_title: str = ""
    song_artist: str = ""
    performance_type: str = "unknown"
    instrument: str = ""
    classifier_confidence: float = 0.0
    visual_confidence: float = 0.0
    audio_confidence: float = 0.0
    model_provider: str = "heuristic"
    model_explanation: str = ""
    recognition_confidence: float = 0.0
    status: str = "review"
    collected_at: str = ""


SCHEMA = """
CREATE TABLE IF NOT EXISTS reels (
    id TEXT PRIMARY KEY,
    reel_url TEXT NOT NULL UNIQUE,
    username TEXT,
    profile_url TEXT,
    profile_photo_url TEXT,
    instagram_id TEXT,
    caption TEXT,
    source_kind TEXT,
    source_query TEXT,
    video_url TEXT,
    local_video_path TEXT,
    mp3_path TEXT,
    song_title TEXT,
    song_artist TEXT,
    performance_type TEXT,
    instrument TEXT,
    classifier_confidence REAL DEFAULT 0,
    recognition_confidence REAL DEFAULT 0,
    status TEXT DEFAULT 'review',
    video_sha256 TEXT,
    audio_sha256 TEXT,
    collected_at TEXT,
    updated_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_reels_username ON reels(username);
CREATE INDEX IF NOT EXISTS idx_reels_status ON reels(status);
CREATE INDEX IF NOT EXISTS idx_reels_song ON reels(song_title, song_artist);
"""


def connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript(SCHEMA)
    existing = {row[1] for row in db.execute('PRAGMA table_info(reels)').fetchall()}
    migrations = {
        'visual_confidence': 'REAL DEFAULT 0',
        'audio_confidence': 'REAL DEFAULT 0',
        'model_provider': "TEXT DEFAULT 'heuristic'",
        'model_explanation': "TEXT DEFAULT ''",
    }
    for column, definition in migrations.items():
        if column not in existing:
            db.execute(f'ALTER TABLE reels ADD COLUMN {column} {definition}')
    db.commit()
    return db


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def classify_record(record: ReelRecord) -> ReelRecord:
    """Explainable first-pass filter; later replace with a calibrated multimodal model."""
    text = f"{record.caption} {record.source_query}".lower()
    singing_terms = ["sing", "singer", "singing", "vocal", "vocals", "cover", "coversong", "acapella", "a cappella", "karaoke", "unplugged", "live music"]
    instrument_terms = {
        "guitar": "guitar", "piano": "piano", "keyboard": "keyboard", "drum": "drums",
        "tabla": "tabla", "violin": "violin", "flute": "flute", "veena": "veena",
        "mridangam": "mridangam", "harmonium": "harmonium", "sax": "saxophone",
        "ukulele": "ukulele", "percussion": "percussion", "instrument": "instrument",
    }
    nonperformance_terms = ["sponsored", "advertisement", "promo", "fashion", "makeup", "restaurant", "travel vlog", "real estate", "gym workout", "dance challenge"]
    singing_hits = sum(1 for term in singing_terms if term in text)
    instrument = next((value for term, value in instrument_terms.items() if term in text), "")
    explicit_live = any(term in text for term in ["live", "session", "performance", "performing", "acoustic"])
    negative_hits = sum(1 for term in nonperformance_terms if term in text)
    source_music_hint = any(term in record.source_query.lower() for term in ["cover", "sing", "music", "guitar", "piano", "vocal", "instrument"])
    score = 0.08 + min(singing_hits, 3) * 0.16 + (0.28 if instrument else 0) + (0.12 if explicit_live else 0) + (0.10 if source_music_hint else 0) - min(negative_hits, 2) * 0.12
    record.classifier_confidence = round(max(0.02, min(score, 0.97)), 2)
    record.instrument = instrument
    if instrument and singing_hits:
        record.performance_type = "singing_and_instrument"
    elif instrument:
        record.performance_type = "instrument"
    elif singing_hits:
        record.performance_type = "singing"
    else:
        record.performance_type = "unknown"
    record.status = "review"
    return record


def upsert_record(record: ReelRecord, db: sqlite3.Connection | None = None) -> tuple[str, bool]:
    own = db is None
    db = db or connect()
    if not record.collected_at:
        record.collected_at = utc_now()
    record = classify_record(record)
    existing = db.execute("SELECT id FROM reels WHERE reel_url = ?", (record.reel_url,)).fetchone()
    record_id = existing["id"] if existing else uuid.uuid4().hex
    fields = asdict(record)
    fields.update({"id": record_id, "updated_at": utc_now()})
    columns = list(fields.keys()) + ["updated_at"] if "updated_at" not in fields else list(fields.keys())
    values = [fields[c] for c in columns]
    if existing:
        assignments = ", ".join(f"{c} = ?" for c in columns if c != "id")
        db.execute(f"UPDATE reels SET {assignments} WHERE id = ?", [fields[c] for c in columns if c != "id"] + [record_id])
    else:
        db.execute(f"INSERT INTO reels ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})", values)
    db.commit()
    if own:
        db.close()
    return record_id, not bool(existing)


def import_records(records: Iterable[dict[str, Any]], source_kind: str = "", source_query: str = "") -> dict[str, int]:
    db = connect()
    added = updated = skipped = 0
    for raw in records:
        reel_url = str(raw.get("reel_url") or raw.get("url") or "").strip()
        if not reel_url or "instagram.com" not in reel_url:
            skipped += 1
            continue
        raw = {k: v for k, v in raw.items() if k in ReelRecord.__dataclass_fields__}
        raw["reel_url"] = reel_url
        if source_kind:
            raw["source_kind"] = source_kind
        if source_query:
            raw["source_query"] = source_query
        _, was_added = upsert_record(ReelRecord(**raw), db)
        added += int(was_added)
        updated += int(not was_added)
    db.close()
    return {"added": added, "updated": updated, "skipped": skipped}


def records(query: str = "", status: str = "", limit: int = 1000) -> list[dict[str, Any]]:
    db = connect()
    where, params = [], []
    if query:
        like = f"%{query}%"
        where.append("(username LIKE ? OR caption LIKE ? OR song_title LIKE ? OR song_artist LIKE ? OR source_query LIKE ?)")
        params.extend([like] * 5)
    if status:
        where.append("status = ?")
        params.append(status)
    sql = "SELECT * FROM reels" + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY collected_at DESC LIMIT ?"
    params.append(min(max(int(limit), 1), 5000))
    rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    db.close()
    return rows


def stats() -> dict[str, int]:
    db = connect()
    total = db.execute("SELECT COUNT(*) FROM reels").fetchone()[0]
    accepted = db.execute("SELECT COUNT(*) FROM reels WHERE status = 'accepted'").fetchone()[0]
    review = db.execute("SELECT COUNT(*) FROM reels WHERE status = 'review'").fetchone()[0]
    duplicates = db.execute("SELECT COUNT(*) FROM reels WHERE status = 'duplicate'").fetchone()[0]
    db.close()
    return {"total": total, "accepted": accepted, "review": review, "duplicates": duplicates}


def update_status(record_id: str, status: str) -> None:
    if status not in {"review", "accepted", "rejected", "duplicate"}:
        raise ValueError("invalid status")
    db = connect()
    db.execute("UPDATE reels SET status = ?, updated_at = ? WHERE id = ?", (status, utc_now(), record_id))
    db.commit(); db.close()


def find_ffmpeg() -> str | None:
    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg
    vendor_dir = BASE_DIR / ".vendor"
    if vendor_dir.exists():
        sys.path.insert(0, str(vendor_dir))
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return None
    return None


def process_video(video_path: str, reel_url: str, username: str = "", song_title: str = "", song_artist: str = "") -> dict[str, Any]:
    source = Path(video_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        raise RuntimeError("FFmpeg is required for MP3 conversion. Install the project requirements and retry.")
    dest = MEDIA_DIR / f"{slug(username)}_{sha256_file(source)[:12]}.mp3"
    cmd = [ffmpeg, "-y", "-i", str(source), "-vn", "-codec:a", "libmp3lame", "-q:a", "2", "-metadata", f"artist={username}", "-metadata", f"title={song_title or 'Instagram performance'}", "-metadata", "album=Instagram Live Performances", "-metadata", f"comment=Original reel: {reel_url}", str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    rec = ReelRecord(reel_url=reel_url, username=username, song_title=song_title, song_artist=song_artist, local_video_path=str(source), mp3_path=str(dest), video_sha256=sha256_file(source), collected_at=utc_now(), status="review")
    db = connect(); rec = classify_record(rec)
    rid, _ = upsert_record(rec, db)
    db.execute("UPDATE reels SET audio_sha256 = ?, updated_at = ? WHERE id = ?", (sha256_file(dest), utc_now(), rid)); db.commit(); db.close()
    return {"id": rid, "mp3_path": str(dest), "video_sha256": rec.video_sha256, "audio_sha256": sha256_file(dest)}


def export_credits(fmt: str, output: str | None = None) -> str:
    rows = records(limit=5000)
    output_path = Path(output).expanduser() if output else EXPORT_DIR / f"credits.{fmt}"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    public_fields = ["id", "song_title", "song_artist", "username", "profile_url", "profile_photo_url", "instagram_id", "reel_url", "caption", "performance_type", "instrument", "classifier_confidence", "recognition_confidence", "status", "mp3_path", "collected_at"]
    if fmt == "json":
        output_path.write_text(json.dumps([{k: row.get(k, "") for k in public_fields} for row in rows], indent=2, ensure_ascii=False), encoding="utf-8")
    elif fmt == "csv":
        with output_path.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=public_fields); writer.writeheader(); writer.writerows({k: row.get(k, "") for k in public_fields} for row in rows)
    else:
        raise ValueError("format must be csv or json")
    return str(output_path)
