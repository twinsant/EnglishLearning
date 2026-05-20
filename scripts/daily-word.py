#!/usr/bin/env python3
"""从单词本随机取一个学习中的单词，写入 JSON 文件供 heartbeat 检测"""

import sqlite3
import json
import random
import os
from datetime import date

DB_PATH = os.path.expanduser("~/GitHub/EnglishLearning/单词本/words.db")
OUTPUT = os.path.expanduser("~/.openclaw/workspace/daily-word.json")


def pick_word():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT word, phonetic, pos, meaning_cn, samples, lookup_count FROM words WHERE mastered=0 ORDER BY RANDOM() LIMIT 1"
    ).fetchall()
    conn.close()

    if not rows:
        return None

    r = rows[0]
    word = {
        "word": r[0],
        "phonetic": r[1] or "",
        "pos": r[2] or "",
        "meaning": r[3] or "",
        "samples": json.loads(r[4]) if r[4] else [],
        "count": r[5],
        "date": date.today().isoformat(),
    }
    return word


def main():
    word = pick_word()
    if not word:
        print("没有学习中单词")
        return

    with open(OUTPUT, "w") as f:
        json.dump(word, f, ensure_ascii=False, indent=2)

    print(f"📖 今日单词: {word['word']} — {word['meaning']}")


if __name__ == "__main__":
    main()
