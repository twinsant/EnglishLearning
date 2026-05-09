#!/usr/bin/env python3
"""英语单词查阅记录工具

用法:
    python3 lookup.py <word>           # 查单词并记录
    python3 lookup.py --list           # 列出生词 (不含已掌握)
    python3 lookup.py --list --all     # 列出所有词
    python3 lookup.py --stats          # 统计信息
    python3 lookup.py --master <word>  # 标记为已掌握
    python3 lookup.py --unmaster <word> # 取消已掌握标记
"""

import sqlite3
import json
import sys
import os
from datetime import date
from urllib.request import urlopen, Request
from urllib.parse import quote

DB_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(DB_DIR, "words.db")
API_BASE = "https://www.twinsant.com/fapi/w/"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS words (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT NOT NULL UNIQUE,
            phonetic TEXT,
            pos TEXT,
            meaning_cn TEXT,
            meaning_en TEXT,
            synonyms TEXT,
            antonyms TEXT,
            close_synonyms TEXT,
            samples TEXT,
            root TEXT,
            affixes TEXT,
            etymology TEXT,
            first_date TEXT NOT NULL,
            last_date TEXT NOT NULL,
            lookup_count INTEGER DEFAULT 1,
            mastered INTEGER DEFAULT 0
        )
    """)
    # 兼容旧表迁移：如果没有 mastered 列则添加
    cols = [r[1] for r in conn.execute("PRAGMA table_info(words)").fetchall()]
    if "mastered" not in cols:
        conn.execute("ALTER TABLE words ADD COLUMN mastered INTEGER DEFAULT 0")
    conn.commit()
    conn.close()


def fetch_word(word):
    """从 API 获取单词信息"""
    url = API_BASE + quote(word)
    req = Request(url, headers={"User-Agent": "EnglishLearning/1.0"})
    try:
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            if data.get("code") == 200:
                return data["data"]
    except Exception as e:
        print(f"⚠️  API 查询失败: {e}")
    return None


def lookup(word):
    """查单词并写入数据库"""
    word = word.strip().lower()
    if not word:
        print("❌ 请输入要查的单词")
        return

    init_db()
    conn = get_db()
    today = date.today().isoformat()

    row = conn.execute("SELECT * FROM words WHERE word = ?", (word,)).fetchone()

    if row:
        new_count = row["lookup_count"] + 1
        conn.execute(
            "UPDATE words SET last_date = ?, lookup_count = ?, mastered = 0 WHERE word = ?",
            (today, new_count, word),
        )
        conn.commit()
        conn.close()
        mastered_tag = " ✅已掌握" if row["mastered"] else ""
        print(f"📖 {word} 第 {new_count} 次查阅 (首次: {row['first_date']}){mastered_tag}")
        print_word_info(row)
        return

    print(f"🔍 查询 {word} ...")
    info = fetch_word(word)

    if info:
        samples = json.dumps(info.get("samples", []), ensure_ascii=False)
        synonyms = json.dumps(info.get("synonyms", []), ensure_ascii=False)
        antonyms = json.dumps(info.get("antonyms", []), ensure_ascii=False)
        close_synonyms = json.dumps(info.get("close_synonyms", []), ensure_ascii=False)
        affixes = json.dumps(info.get("affixes"), ensure_ascii=False) if info.get("affixes") else None

        conn.execute(
            """INSERT INTO words
            (word, phonetic, pos, meaning_cn, meaning_en, synonyms, antonyms,
             close_synonyms, samples, root, affixes, etymology, first_date, last_date, lookup_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
            (
                word,
                info.get("phonetic"),
                info.get("pos"),
                info.get("meaning_cn"),
                info.get("meaning_en"),
                synonyms,
                antonyms,
                close_synonyms,
                samples,
                info.get("root"),
                affixes,
                info.get("etymology"),
                today,
                today,
            ),
        )
    else:
        conn.execute(
            "INSERT INTO words (word, first_date, last_date, lookup_count) VALUES (?, ?, ?, 1)",
            (word, today, today),
        )

    conn.commit()
    conn.close()
    print(f"✅ {word} 已添加到生词本")
    if info:
        print_word_info_from_dict(info)


def print_word_info(row):
    info = dict(row)
    print_word_info_from_dict(info)


def print_word_info_from_dict(info):
    if info.get("phonetic"):
        print(f"   音标: /{info['phonetic']}/")
    if info.get("pos"):
        print(f"   词性: {info['pos']}")
    if info.get("meaning_cn"):
        print(f"   中文: {info['meaning_cn']}")
    if info.get("meaning_en"):
        print(f"   英文: {info['meaning_en']}")
    if info.get("etymology"):
        print(f"   词源: {info['etymology']}")

    for field, label in [
        ("synonyms", "近义词"),
        ("antonyms", "反义词"),
        ("close_synonyms", "近似词"),
    ]:
        val = info.get(field)
        if val:
            try:
                items = json.loads(val) if isinstance(val, str) else val
                if items:
                    print(f"   {label}: {', '.join(items)}")
            except (json.JSONDecodeError, TypeError):
                pass

    if info.get("samples"):
        try:
            samples = json.loads(info["samples"]) if isinstance(info["samples"], str) else info["samples"]
            if samples:
                print("   例句:")
                for s in samples:
                    print(f"     • {s}")
        except (json.JSONDecodeError, TypeError):
            pass

    if info.get("root"):
        print(f"   词根: {info['root']}")
    if info.get("affixes"):
        try:
            aff = json.loads(info["affixes"]) if isinstance(info["affixes"], str) else info["affixes"]
            if aff:
                print(f"   词缀: {', '.join(aff) if isinstance(aff, list) else aff}")
        except (json.JSONDecodeError, TypeError):
            pass


def list_words(show_all=False):
    init_db()
    conn = get_db()
    if show_all:
        rows = conn.execute(
            "SELECT word, meaning_cn, lookup_count, first_date, last_date, mastered FROM words ORDER BY last_date DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT word, meaning_cn, lookup_count, first_date, last_date, mastered FROM words WHERE mastered = 0 ORDER BY last_date DESC"
        ).fetchall()
    conn.close()

    label = "全部" if show_all else "生词"
    if not rows:
        print(f"📭 {label}本为空")
        return

    print(f"📚 共 {len(rows)} 个{label}:\n")
    header = f"{'单词':<20} {'释义':<20} {'查阅':<6} {'首次':<12} {'最近':<12}"
    if show_all:
        header += f" {'状态':<6}"
    print(header)
    print("-" * (78 if show_all else 72))
    for r in rows:
        meaning = (r["meaning_cn"] or "-")[:18]
        line = f"{r['word']:<20} {meaning:<20} {r['lookup_count']:<6} {r['first_date']:<12} {r['last_date']:<12}"
        if show_all:
            status = "✅" if r["mastered"] else "📖"
            line += f" {status:<6}"
        print(line)


def stats():
    init_db()
    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM words").fetchone()["c"]
    learning = conn.execute("SELECT COUNT(*) as c FROM words WHERE mastered = 0").fetchone()["c"]
    mastered = conn.execute("SELECT COUNT(*) as c FROM words WHERE mastered = 1").fetchone()["c"]
    total_lookups = conn.execute("SELECT SUM(lookup_count) as c FROM words").fetchone()["c"] or 0
    today_str = date.today().isoformat()
    today_count = conn.execute(
        "SELECT COUNT(*) as c FROM words WHERE last_date = ?", (today_str,)
    ).fetchone()["c"]
    top = conn.execute(
        "SELECT word, lookup_count, mastered FROM words ORDER BY lookup_count DESC LIMIT 10"
    ).fetchall()
    conn.close()

    print(f"📊 生词本统计")
    print(f"   学习中: {learning}  已掌握: {mastered}  总计: {total}")
    print(f"   总查阅次数: {total_lookups}")
    print(f"   今日查阅: {today_count} 个")
    if mastered > 0 and total > 0:
        print(f"   掌握率: {mastered}/{total} = {mastered*100//total}%")
    if top:
        print(f"\n🔝 查阅最多的词:")
        for r in top:
            bar = "█" * min(r["lookup_count"], 20)
            tag = " ✅" if r["mastered"] else ""
            print(f"   {r['word']:<16} {r['lookup_count']:>3} {bar}{tag}")


def set_mastered(word, mastered=True):
    """标记单词为已掌握/未掌握"""
    word = word.strip().lower()
    if not word:
        print("❌ 请输入单词")
        return
    init_db()
    conn = get_db()
    row = conn.execute("SELECT * FROM words WHERE word = ?", (word,)).fetchone()
    if not row:
        print(f"❌ 生词本中没有 '{word}'")
        conn.close()
        return
    val = 1 if mastered else 0
    conn.execute("UPDATE words SET mastered = ? WHERE word = ?", (val, word))
    conn.commit()
    conn.close()
    status = "✅ 已掌握" if mastered else "📖 回到生词本"
    print(f"{status}: {word}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "--list":
        show_all = "--all" in sys.argv
        list_words(show_all)
    elif cmd == "--stats":
        stats()
    elif cmd == "--master":
        if len(sys.argv) < 3:
            print("用法: python3 lookup.py --master <word>")
        else:
            set_mastered(sys.argv[2], mastered=True)
    elif cmd == "--unmaster":
        if len(sys.argv) < 3:
            print("用法: python3 lookup.py --unmaster <word>")
        else:
            set_mastered(sys.argv[2], mastered=False)
    else:
        lookup(cmd)
