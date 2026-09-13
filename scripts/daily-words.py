#!/usr/bin/env python3
"""每天随机抽取 20 个未掌握单词，输出带序号的卡片
抽词后自动检测缺失字段（音标/词义/词性），调用词典 API 补全并写回数据库"""
import sqlite3
import json
import sys
import random
import urllib.request
from pathlib import Path

DB = Path.home() / "GitHub/EnglishLearning/单词本/words.db"
OUT = Path.home() / ".openclaw/workspace/daily-words.json"
API = "https://www.twinsant.com/fapi/w/{}"


def get_unmastered(db_path, limit=20):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT word, phonetic, meaning_cn, pos, samples
        FROM words
        WHERE mastered = 0
        ORDER BY lookup_count ASC, RANDOM()
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return rows


def fetch_word(word):
    """调用词典 API，返回 data 字段；失败返回 None"""
    try:
        req = urllib.request.Request(API.format(word), headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.load(resp)
        if data.get("code") == 200 and data.get("data"):
            return data["data"]
    except Exception as e:
        print(f"  ⚠️ {word} API 调用失败: {e}", file=sys.stderr)
    return None


def repair_word(word):
    """检查 word 在库中是否缺字段，缺失则调 API 补全。返回是否补全"""
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    r = conn.execute(
        "SELECT phonetic, meaning_cn, pos FROM words WHERE word=?", (word,)
    ).fetchone()
    if not r:
        conn.close()
        return False
    # 判定缺失：音标/中义/词性任一为空，或中义只是单词本身（无意义占位）
    missing = not (r["phonetic"] and r["meaning_cn"] and r["pos"])
    if not missing and (r["meaning_cn"] == word or len(r["meaning_cn"]) <= 1):
        missing = True
    conn.close()
    if not missing:
        return False

    d = fetch_word(word)
    if not d:
        return False
    conn = sqlite3.connect(DB)
    conn.execute("""UPDATE words SET
        phonetic=?, pos=?, meaning_cn=?, meaning_en=?,
        synonyms=?, antonyms=?, close_synonyms=?, samples=?,
        root=?, affixes=?, etymology=?
        WHERE word=?""", (
        d.get("phonetic"), d.get("pos"), d.get("meaning_cn"), d.get("meaning_en"),
        json.dumps(d.get("synonyms", []), ensure_ascii=False),
        json.dumps(d.get("antonyms", []), ensure_ascii=False),
        json.dumps(d.get("close_synonyms", []), ensure_ascii=False),
        json.dumps(d.get("samples", []), ensure_ascii=False),
        d.get("root"), json.dumps(d.get("affixes", []), ensure_ascii=False),
        d.get("etymology"), word
    ))
    conn.commit()
    conn.close()
    print(f"  🔧 已补全: {word} -> {d.get('meaning_cn')}")
    return True


def main():
    rows = get_unmastered(DB, limit=20)
    if not rows:
        print("没有待学习的单词")
        return

    # 第一步：自动补全缺失词条（抽到的词里若有空壳，先修好）
    print("🔍 检查缺失词条...")
    for r in rows:
        repair_word(r["word"])

    # 第二步：重新读取（补全后可能字段已更新）
    rows = get_unmastered(DB, limit=20)

    words = []
    for i, r in enumerate(rows, 1):
        word = {
            "no": i,
            "word": r["word"],
            "phonetic": r["phonetic"] or "",
            "meaning": r["meaning_cn"] or "",
            "pos": r["pos"] or "",
        }
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
