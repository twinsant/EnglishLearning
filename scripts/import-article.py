#!/usr/bin/env python3
"""
从网页链接抓取英文文章 → 保存原文 → 提取全部单词入生词本

用法:
  python3 import-article.py <url>                    # 完整流程
  python3 import-article.py <url> --save-only        # 只保存原文
  python3 import-article.py <url> --words-only       # 只导入生词（需要已有原文）

依赖: curl, python3, sqlite3
"""
import sys
import os
import re
import json
import sqlite3
import subprocess
from pathlib import Path
from urllib.parse import urlparse

PROJECT = Path.home() / "GitHub/EnglishLearning"
LIB = PROJECT / "lib"
DB = PROJECT / "单词本/words.db"
LOOKUP = PROJECT / "单词本/lookup.py"


def fetch_raw(url):
    """用 curl 抓取 Wikisource raw 或通用网页文本"""
    parsed = urlparse(url)
    
    # Wikisource: 用 action=raw
    if "wikisource" in parsed.netloc:
        raw_url = f"{parsed.scheme}://{parsed.netloc}/w/index.php?title={parsed.path.split('/')[-1]}&action=raw"
    elif "wikipedia" in parsed.netloc:
        title = parsed.path.split('/')[-1]
        raw_url = f"{parsed.scheme}://{parsed.netloc}/w/index.php?title={title}&action=raw"
    else:
        raw_url = url

    print(f"⬇️  抓取: {raw_url}")
    result = subprocess.run(
        ["curl", "-sL", "--max-time", "60",
         "-H", "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
         raw_url],
        capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"❌ 抓取失败: {result.stderr[:200]}")
        sys.exit(1)
    return result.stdout


def clean_wiki(text):
    """清洗 Wiki 模板标记"""
    # 移除 {{header ...}} 模板
    text = re.sub(r'\{\{header.*?\}\}', '', text, flags=re.DOTALL)
    # 移除 {{PD-US...}} 等尾部模板
    text = re.sub(r'\{\{PD-US.*?\}\}', '', text, flags=re.DOTALL)
    text = re.sub(r'\{\{DEFAULTSORT:.*?\}\}', '', text, flags=re.DOTALL)
    # 移除 listen 模板
    text = re.sub(r'\{\{listen.*?\}\}', '', text, flags=re.DOTALL)
    # 清理多余的 }} 残留
    text = text.replace('}}', '')
    # 合并多个空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def slugify(text):
    """生成文件名"""
    name = re.sub(r'[^\w\s-]', '', text.lower())
    name = re.sub(r'[-\s]+', '-', name)
    return name.strip('-')[:60]


def save_text(text, url):
    """保存原文到 lib/"""
    LIB.mkdir(parents=True, exist_ok=True)
    # 从 URL 提取文件名
    path = urlparse(url).path.strip('/')
    filename = slugify(path.split('/')[-1]) if path else slugify(urlparse(url).netloc)
    if not filename:
        filename = "article"
    filepath = LIB / f"{filename}.txt"
    filepath.write_text(text, encoding='utf-8')
    print(f"📄 原文已保存: {filepath}  ({len(text)} 字符)")
    return filepath


def extract_words(text):
    """提取所有唯一单词"""
    words = re.findall(r'[a-zA-Z]+', text)
    return sorted(set(w.lower() for w in words))


def import_to_db(words):
    """将单词导入生词本"""
    # 先查已存在
    conn = sqlite3.connect(str(DB))
    existing = set(r[0] for r in conn.execute("SELECT word FROM words").fetchall())
    conn.close()
    
    new_words = [w for w in words if w not in existing]
    skip = len(words) - len(new_words)
    
    print(f"📊 去重: {len(words)} → {len(new_words)} 个新词 (已有 {skip})")
    
    if not new_words:
        print("✅ 没有新词需要添加")
        return 0
    
    # 批量导入
    total = len(new_words)
    for i, word in enumerate(new_words, 1):
        subprocess.run(
            [sys.executable, str(LOOKUP), word],
            capture_output=True, timeout=15
        )
        if i % 50 == 0:
            print(f"  [{i}/{total}]")
    
    print(f"✅ 已导入 {total} 个新词")
    return total


def show_stats():
    """显示生词本统计"""
    result = subprocess.run(
        [sys.executable, str(LOOKUP), "--stats"],
        capture_output=True, text=True, timeout=10
    )
    print(result.stdout)


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help', 'help'):
        print(__doc__)
        sys.exit(0)
    url = sys.argv[1]

    save_only = "--save-only" in sys.argv
    words_only = "--words-only" in sys.argv

    if words_only:
        # 从已有文件提取单词
        filepath = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else None
        if not filepath:
            # 找最新的 lib 文件
            files = sorted(LIB.glob("*.txt"), key=os.path.getmtime, reverse=True)
            if not files:
                print("❌ lib/ 目录没有文件，请先 --save-only")
                sys.exit(1)
            filepath = str(files[0])
        print(f"📖 读取: {filepath}")
        text = Path(filepath).read_text(encoding='utf-8')
    else:
        text = fetch_raw(url)
        if "wikisource" in url or "wikipedia" in url:
            text = clean_wiki(text)
        
        if not save_only:
            save_text(text, url)

    if save_only:
        print("✅ 仅保存，跳过生词导入")
        return

    words = extract_words(text)
    print(f"🔤 提取单词: {len(words)} 个")
    import_to_db(words)
    show_stats()


if __name__ == "__main__":
    main()
