#!/usr/bin/env python3
"""Pull aiLearnEnglish mastery events into the local words database."""
import argparse
import json
import os
import sqlite3
import sys
from datetime import date, datetime, timezone
from urllib.parse import quote
from urllib.request import Request, urlopen

DB = os.path.expanduser("~/GitHub/EnglishLearning/单词本/words.db")
API_ROOT = "https://www.twinsant.com/fapi"


def init_sync_meta(conn):
    conn.execute(
        """CREATE TABLE IF NOT EXISTS sync_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )


def get_cursor(conn):
    row = conn.execute(
        "SELECT value FROM sync_meta WHERE key = 'learning_events_cursor'"
    ).fetchone()
    return row[0] if row else None


def set_cursor(conn, cursor):
    conn.execute(
        """INSERT INTO sync_meta(key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at""",
        ("learning_events_cursor", cursor, datetime.now(timezone.utc).isoformat()),
    )


def request_json(url, token):
    request = Request(url, headers={"X-Sync-Token": token, "User-Agent": "EnglishLearning/sync"})
    with urlopen(request, timeout=15) as response:
        return json.loads(response.read())


def fetch_events(api_root, token, cursor, limit):
    url = f"{api_root}/english/learning-events?limit={limit}"
    if cursor:
        url += f"&after={quote(cursor)}"
    response = request_json(url, token)
    if response.get("code") != 200:
        raise RuntimeError(f"event pull failed: {response}")
    return response["data"]


def fetch_word(api_root, word):
    response = request_json(f"{api_root}/w/{quote(word)}", "")
    if response.get("code") != 200 or not response.get("data"):
        raise RuntimeError(f"word lookup failed: {word}")
    return response["data"]


def insert_word(conn, word, info):
    today = date.today().isoformat()
    values = {
        "phonetic": info.get("phonetic", ""),
        "pos": info.get("pos", ""),
        "meaning_cn": info.get("meaning_cn", ""),
        "meaning_en": info.get("meaning_en", ""),
        "synonyms": json.dumps(info.get("synonyms", []), ensure_ascii=False),
        "antonyms": json.dumps(info.get("antonyms", []), ensure_ascii=False),
        "close_synonyms": json.dumps(info.get("close_synonyms", []), ensure_ascii=False),
        "samples": json.dumps(info.get("samples", []), ensure_ascii=False),
        "root": info.get("root", ""),
        "affixes": json.dumps(info.get("affixes"), ensure_ascii=False),
        "etymology": info.get("etymology", ""),
    }
    conn.execute(
        """INSERT INTO words
        (word, phonetic, pos, meaning_cn, meaning_en, synonyms, antonyms,
         close_synonyms, samples, root, affixes, etymology, first_date, last_date, lookup_count, mastered)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)""",
        (word, values["phonetic"], values["pos"], values["meaning_cn"], values["meaning_en"],
         values["synonyms"], values["antonyms"], values["close_synonyms"], values["samples"],
         values["root"], values["affixes"], values["etymology"], today, today, 1),
    )


def apply_events(conn, events, api_root, next_cursor=None, dry_run=False):
    if dry_run:
        return len(events)

    conn.execute("BEGIN")
    try:
        for event in events:
            word = event["word"].strip().lower()
            mastered = 1 if event["state"] == "mastered" else 0
            row = conn.execute("SELECT 1 FROM words WHERE word = ?", (word,)).fetchone()
            if row is None:
                insert_word(conn, word, fetch_word(api_root, word))
            else:
                conn.execute("UPDATE words SET mastered = ? WHERE word = ?", (mastered, word))
            conn.execute("UPDATE words SET mastered = ? WHERE word = ?", (mastered, word))
        if next_cursor:
            set_cursor(conn, next_cursor)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return len(events)


def sync_once(db_path, api_root, token, batch_size=100, dry_run=False):
    conn = sqlite3.connect(db_path)
    init_sync_meta(conn)
    cursor = get_cursor(conn)
    total = 0
    try:
        while True:
            page = fetch_events(api_root, token, cursor, batch_size)
            events = page.get("items", [])
            if not events:
                break
            next_cursor = page.get("next_cursor")
            apply_events(conn, events, api_root, next_cursor, dry_run)
            if not next_cursor or dry_run:
                break
            cursor = next_cursor
            total += len(events)
            if len(events) < batch_size:
                break
    finally:
        conn.close()
    return total, cursor


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--db-path", default=DB)
    parser.add_argument("--endpoint", default=os.getenv("ENGLISH_SYNC_API_URL", API_ROOT))
    parser.add_argument("--batch-size", type=int, default=100)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--status", action="store_true")
    args = parser.parse_args()

    conn = sqlite3.connect(args.db_path)
    init_sync_meta(conn)
    cursor = get_cursor(conn)
    conn.commit()
    conn.close()
    if args.status:
        print(cursor or "未同步任何事件")
        return

    token = os.getenv("ENGLISH_SYNC_TOKEN")
    if not token:
        print("ENGLISH_SYNC_TOKEN is required", file=sys.stderr)
        raise SystemExit(1)
    total, new_cursor = sync_once(args.db_path, args.endpoint.rstrip("/"), token, args.batch_size, args.dry_run)
    print(f"同步 {total} 条学习状态事件，cursor={new_cursor or 'none'}")


if __name__ == "__main__":
    main()
