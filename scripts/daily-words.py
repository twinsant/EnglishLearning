#!/usr/bin/env python3
"""每天随机抽取 10 个未掌握单词，输出带序号的卡片"""
import sqlite3
import json
import sys
import random
from pathlib import Path

DB = Path.home() / "GitHub/EnglishLearning/单词本/words.db"
OUT = Path.home() / ".openclaw/workspace/daily-words.json"

def get_unmastered(db_path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT word, phonetic, meaning_cn, pos, samples
        FROM words
        WHERE mastered = 0
        ORDER BY lookup_count ASC, RANDOM()
        LIMIT 10
    """).fetchall()
    conn.close()
    return rows

def main():
    rows = get_unmastered(DB)
    if not rows:
        print("没有待学习的单词")
        return

    words = []
    for i, r in enumerate(rows, 1):
        word = {
            "no": i,
            "word": r["word"],
            "phonetic": r["phonetic"] or "",
            "meaning": r["meaning_cn"] or "",
            "pos": r["pos"] or "",
        }
        # 取第一条例句
        if r["samples"]:
            try:
                samples = json.loads(r["samples"])
                if samples:
                    word["sample"] = samples[0]
            except json.JSONDecodeError:
                word["sample"] = ""
        else:
            word["sample"] = ""
        words.append(word)

    from datetime import date
    payload = {
        "date": date.today().isoformat(),
        "words": words,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"✅ 已写入 {len(words)} 个单词 -> {OUT}")
    for w in words:
        print(f"  {w['no']}. {w['word']} — {w['meaning']}")

if __name__ == "__main__":
    main()
