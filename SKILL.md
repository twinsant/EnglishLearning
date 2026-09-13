---
name: daily-english-words
description: "每日英语单词推送与生词本管理。触发词：推送今日单词、今日英语、英语学习清单、生词复习、单词打卡、每日单词、标记掌握/未掌握。从生词本抽取未掌握单词生成学习卡片推送，处理用户掌握/未掌握回复，自动补全缺失词条。"
---

# 每日英语单词推送

从生词本（words.db）抽取未掌握单词，生成学习清单卡片推送到 QQ，并处理用户的掌握/未掌握标记。

## 资源路径

| 资源 | 路径 |
|------|------|
| 生词本数据库 | `~/GitHub/EnglishLearning/单词本/words.db` |
| 抽取脚本 | `~/GitHub/EnglishLearning/scripts/daily-words.py` |
| 生词本管理脚本 | `~/GitHub/EnglishLearning/单词本/lookup.py` |
| 词典 API | `https://www.twinsant.com/fapi/w/<word>` |
| 推送中间文件 | `~/.openclaw/workspace/daily-words.json` |

## 推送流程

1. 运行抽取脚本：`python3 ~/GitHub/EnglishLearning/scripts/daily-words.py`
   - 完成标准：脚本打印「已写入 N 个单词」且无报错
   - 脚本抽取 20 个未掌握单词（`ORDER BY lookup_count ASC, RANDOM()`）
   - 脚本自动检测缺失词条（音标/词义/词性为空），调词典 API 补全后写回数据库
2. 读取 `~/.openclaw/workspace/daily-words.json`
   - 完成标准：拿到 `words` 数组，每项含 `no/word/phonetic/meaning/pos/sample` 字段
3. 按卡片格式输出并推送（见下方格式）

## 卡片输出格式

```
📖 今日英语 · 学习清单
══════════════════════════
1. **escorted** /ɪˈskɔːrtɪd/
   verb · 护送
   💬 The security guards escorted the VIP to the event.
...
══════════════════════════
共 20 个单词
回复单词序号标记已掌握，如: 3 7 12
```

## 处理用户回复

用户会回复「序号 已掌握 / 未掌握」，例如 `3 7 12`（掌握）或 `未掌握 5/8/10`（未掌握）。

- 标记已掌握：逐词运行 `python3 ~/GitHub/EnglishLearning/单词本/lookup.py --master <word>`
- 标记未掌握：逐词运行 `python3 ~/GitHub/EnglishLearning/单词本/lookup.py --unmaster <word>`
- 完成标准：脚本返回「回到生词本」或已掌握标记成功，所有序号对应单词都处理完毕

## 缺失词条补全（手动场景）

当用户报告某词「词义缺失」或推送中某词无释义时：

1. 调 API 确认数据：`curl "https://www.twinsant.com/fapi/w/<word>"`，检查 `code==200` 且 `data` 有 `meaning_cn`
2. 用 Python 将 API 返回写入数据库的 `phonetic/pos/meaning_cn/meaning_en/synonyms/antonyms/samples/root/etymology` 字段（参考 lookup.py 的 UPDATE 语句）
3. 完成标准：数据库该词释义非空，`meaning_cn` 有值

## 已知问题

- 生词本混有噪音词（人名 / 乱码 / 单字母，如 sarah、fg、iuuuf），会影响推送质量，可视情况清理或标记 mastered 排除出推送池

## 注意事项

- 数据库文件较大（约 8MB），用 sqlite3/Python 直接读写，不要整库加载
- 私钥/凭据类信息与本文无关，不涉及
