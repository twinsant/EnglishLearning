## Plan: 复用现有单词 API 双向同步

直接扩展 `/Users/twinsant/projects/twinsant/api/fapi` 中现有的 MongoDB 单词服务：EnglishLearning 发布每日词单到同一个 `items` 数据库；aiLearnEnglish 读取词单，并将“掌握/未掌握”作为幂等事件上传；EnglishLearning 每日生成前按游标拉取事件并事务性回写 `words.db`。不改独立的新仓库 `/Users/twinsant/projects/twinsant_fapi`。

**Steps**

### Phase 1: 固定协议与集合
1. 每日词单契约保持当前生成格式：顶层 `date` 为 ISO 日期，`words` 为 1 至 20 项；每项包含 `no`、`word`、`phonetic`、`meaning`、`pos`、`sample`。
2. 学习事件包含客户端 UUID `event_id`、规范化小写 `word`、`state`（`mastered` 或 `unmastered`）、UTC `occurred_at`、`source`（`aiLearnEnglish-ios`）。服务端顺序由 MongoDB `_id` 决定，客户端时间只用于审计，不参与游标推进。
3. 在现有 `items` 数据库新增三个集合，不改变 `friends_words` 的词典缓存结构：
	- `daily_word_lists`：每日词单，`date` 唯一索引。
	- `word_mastery_events`：不可变状态事件，`event_id` 唯一索引，并索引 `word`。
	- `word_mastery_states`：每个 `word` 的最新状态、最近事件 ID 和更新时间，`word` 唯一索引，便于排障和未来状态查询。
4. 鉴权使用单用户 `X-Sync-Token`：词单发布、事件上传、事件拉取都需要令牌；每日词单读取公开。服务端从 `ENGLISH_SYNC_TOKEN` 读取，Python 从同名环境变量读取，iOS 由用户首次输入后保存到 Keychain。

### Phase 2: 扩展 twinsant/api/fapi
5. 新建 `/Users/twinsant/projects/twinsant/api/fapi/english_sync.py`，定义 Pydantic 模型、令牌校验、Mongo collection 获取函数和 `APIRouter`，避免继续膨胀 `main.py`；该模块复用 `request.app.mongodb`，不创建第二个 Mongo client。
6. 在 `/Users/twinsant/projects/twinsant/api/fapi/main.py` 中注册 router，并在现有 `startup_event()` 初始化集合句柄和索引。继续使用已经连接的 `mongodb://localhost:27017` 与 `items` 数据库，保留 `app.words = items.friends_words` 及所有 `/w/*` 行为。
7. 使用独立 `/english/*` 路由，避免静态 `/w/daily` 被现有 `/w/{word}` 捕获：
	- `PUT /english/daily-words`：鉴权，按日期 upsert，返回保存后的 payload。
	- `GET /english/daily-words?date=`：不传日期返回最新，传日期返回指定词单；不存在返回 404。
	- `POST /english/learning-events`：鉴权，批量插入；重复 `event_id` 视为成功但不重复写事件，并按服务端事件顺序更新 `word_mastery_states`。
	- `GET /english/learning-events?after=<cursor>&limit=100`：鉴权，按 Mongo `_id` 升序返回事件和 `next_cursor`；非法 cursor 返回 422。
	Nginx 已将 `https://www.twinsant.com/fapi/` 去前缀代理到该应用，因此公网地址自动为 `/fapi/english/...`，无需改 Nginx。
8. 幂等规则：`event_id` 唯一；同一个上传批次先按 `occurred_at,event_id` 稳定排序，再逐项插入；只有首次插入的事件更新 latest state；重复提交返回已接受的 ID。反向消费以不可变事件为准，不以 latest-state 集合代替事件流。
9. 不增加 Ack 接口：EnglishLearning 把事件应用和 `next_cursor` 更新放在同一个 SQLite 事务；失败不推进，成功即推进。服务端事件不可变，因此断点重试不会丢事件。
10. 在 `/Users/twinsant/projects/twinsant/api/fapi/config.py` 增加 `english_sync_token`，确保生产环境缺失时受保护接口返回 503，而不是使用默认口令；更新该应用的环境变量说明。
11. 新增 `/Users/twinsant/projects/twinsant/api/fapi/tests/test_english_sync.py`，沿用现有 `IsolatedAsyncioTestCase + ASGITransport + AsyncMock` 模式，覆盖：词单发布/同日覆盖/按日与最新读取、鉴权、payload 校验、事件插入、重复 UUID 幂等、同词相反状态、游标分页和非法游标。测试不连接真实 MongoDB。

### Phase 3: EnglishLearning 正向发布与反向应用
12. 重构 `/Users/twinsant/GitHub/EnglishLearning/scripts/daily-words.py`，将 payload 构造、原子本地写入和 HTTP PUT 拆成可测试函数；保留现有选词、词条修复和 `~/.openclaw/workspace/daily-words.json` 输出，再发布到默认 `https://www.twinsant.com/fapi/english/daily-words`。
13. 发布失败时保留本地 JSON，但进程非零退出，便于调度发现并重试；密钥只从 `ENGLISH_SYNC_TOKEN` 读取，不进入仓库。
14. 新建 `/Users/twinsant/GitHub/EnglishLearning/scripts/sync-learning-state.py`。在 `words.db` 中初始化 `sync_meta(key, value, updated_at)`，以 `learning_events_cursor` 保存最后成功应用的 Mongo 游标。
15. 反向同步固定为：读取 cursor -> 分页 GET `/fapi/english/learning-events` -> 在一个 SQLite 事务内按返回顺序更新 `words.mastered` -> 同事务更新 cursor -> 提交 -> 拉下一页。`mastered` 映射为 1，`unmastered` 映射为 0；后到事件覆盖先到事件。
16. 如果事件对应单词不在 SQLite，复用 `/fapi/w/{word}` 获取词典数据并插入；获取失败则整批回滚且不推进 cursor，避免静默丢失状态。脚本提供 `--dry-run`、`--batch-size`、`--status`、`--endpoint` 和 `--db-path`。
17. 调整每日自动化顺序：必须先成功运行 `sync-learning-state.py`，再运行 `daily-words.py`。因此 App 标记 mastered 后，该词会被下一次 `WHERE mastered = 0` 排除；标记 unmastered 后重新进入候选池。
18. 在 `/Users/twinsant/GitHub/EnglishLearning/tests/` 增加标准库单元测试，使用临时 SQLite 与 mock HTTP 覆盖发布、分页应用、缺失词补全、事务回滚、cursor 原子推进、重复执行及 dry-run。
19. 更新 `/Users/twinsant/GitHub/EnglishLearning/SKILL.md` 和 README，记录环境变量、先同步后生成的顺序、失败恢复和状态检查命令。

### Phase 4: aiLearnEnglish 读取与离线上传
20. 新建 `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Models/DailyWords.swift`，定义 API Codable 模型并映射到扩展后的 `Word`；新增展示字段设为可选，确保旧 `/api/words` 数据继续可解码。
21. 在 `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Services/Network.swift` 增加每日词单拉取：先读取 UserDefaults 最近成功缓存，再请求 `https://www.twinsant.com/fapi/english/daily-words`；成功后更新列表、日期与缓存，失败时保留缓存。首次无缓存显示错误和重试，不随机换词。
22. 在 `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Views/MediaView.swift` 新增独立“每日单词”入口，保留“今日复习”；在 `MediaBrowserView.swift` 将 `daily-words` 直接路由至 `FlashCardsView`。
23. 在 `FlashCardsView.swift` 增加每日词单分支，并继续复用现有 `onLearn`/`onStar` 的 Core Data 状态切换；每日卡显示音标、词性、中文释义、例句和词单日期，缓存数据明确标注原始日期。
24. 为 Core Data 增加新 model version 和 `PendingLearningEvent`：`eventID`、`word`、`state`、`occurredAt`、`createdAt`。本地掌握状态修改与事件入队使用同一个 managed object context save，保证离线操作不会丢同步意图。
25. 新建 `SyncTokenStore.swift`，通过 Security framework 保存令牌；新增简洁设置页用于首次输入、更新和清除令牌，不写入源码、Info.plist、UserDefaults 或日志。
26. 新建 `LearningSyncService.swift`：App 启动、进入每日词单页、产生新事件、网络恢复时批量发送队列；服务端确认后按 `event_id` 删除，网络/5xx/401 均保留。发送顺序为 `occurredAt,eventID`。
27. 将新增文件与 Core Data model version 加入 `/Users/twinsant/projects/aiLearnEnglish/ai背单词.xcodeproj/project.pbxproj`，启用轻量迁移，保护已有收藏和掌握数据。

### Phase 5: 验证与上线
28. 在 `/Users/twinsant/projects/twinsant/api/fapi` 运行 `uv run python -m unittest tests/test_word_lookup.py tests/test_english_sync.py`，确认旧词典接口与新同步接口同时通过。
29. 在 `/Users/twinsant/GitHub/EnglishLearning` 运行新增 unittest，并以临时数据库执行 pull -> apply -> cursor 提交 -> 再次 pull 的幂等测试。
30. 在 `/Users/twinsant/projects/aiLearnEnglish` 运行 `xcodebuild -project ai背单词.xcodeproj -scheme aiLearnEnglish -sdk iphonesimulator -configuration Debug build CODE_SIGNING_ALLOWED=NO`；模拟器验证在线词单、离线缓存、离线事件队列、401 保留和网络恢复重发。
31. 严格按顺序上线：为旧 fapi 配置 `ENGLISH_SYNC_TOKEN` -> 提交并推送 `twinsant` 的 `master` -> 用 `/Users/twinsant/projects/twinsant.com/ops/ansible/deploy-fapi-from-git.yml` 部署远端 `/root/projects/twinsant` 并重启 `fapi` -> 冒烟验证接口 -> 配置 EnglishLearning -> 最后运行 App。
32. 端到端验证：本地 daily JSON、Mongo `daily_word_lists`、GET 响应与 App 卡组一致；App 离线产生 mastered/unmastered -> 恢复网络上传 -> Mongo 每个 UUID 仅一条事件 -> Python 拉取更新 SQLite 并推进 cursor -> 重跑无变化 -> 下一次抽词反映最新状态。

**Relevant files**
- `/Users/twinsant/projects/twinsant/api/fapi/main.py` — 复用现有 Mongo 启动连接并注册同步 router。
- `/Users/twinsant/projects/twinsant/api/fapi/english_sync.py` — 每日词单与学习事件 API。
- `/Users/twinsant/projects/twinsant/api/fapi/config.py` — 同步令牌配置。
- `/Users/twinsant/projects/twinsant/api/fapi/tests/test_english_sync.py` — Mock Mongo API 测试。
- `/Users/twinsant/projects/twinsant.com/ops/ansible/deploy-fapi-from-git.yml` — 现有旧 fapi 部署入口。
- `/Users/twinsant/GitHub/EnglishLearning/scripts/daily-words.py` — 生成并发布词单。
- `/Users/twinsant/GitHub/EnglishLearning/scripts/sync-learning-state.py` — 拉取事件并回写 SQLite。
- `/Users/twinsant/GitHub/EnglishLearning/单词本/lookup.py` — 复用词条补全与 mastered 语义。
- `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Services/Network.swift` — 词单拉取和缓存。
- `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Services/LearningSyncService.swift` — 离线事件上传。
- `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Services/SyncTokenStore.swift` — Keychain 令牌。
- `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/Views/FlashCardsView.swift` — 每日卡组和事件产生点。
- `/Users/twinsant/projects/aiLearnEnglish/aiLearnEnglish/aiLearnEnglish.xcdatamodeld` — 待同步事件实体及迁移。

**Verification**
1. 旧 fapi 单元测试必须同时证明 `/w/{word}` 未回归，以及新接口鉴权、Mongo upsert、事件去重和 cursor 分页正确。
2. 使用本地 MongoDB 做一次真实 API 冒烟测试，检查三个新集合的唯一索引和文档结构。
3. EnglishLearning 用临时 SQLite 验证同步事务失败不推进 cursor，成功重跑不重复应用。
4. iOS 验证令牌只存在 Keychain，离线事件在杀进程后仍存在，成功上传后才删除。
5. 生产验证公网路径 `https://www.twinsant.com/fapi/english/...`，无需调整 Nginx。

**Decisions**
- 复用 `twinsant/api/fapi` 现有 MongoDB 连接和 `items` 数据库，不修改新 `twinsant_fapi`。
- 不把每日词单或个人掌握状态直接混入 `friends_words`；使用同库独立集合。
- 反向同步只包含 mastered/unmastered，不同步收藏、复习次数或完整历史。
- 暂按单用户令牌鉴权，App 内首次输入并存 Keychain。
- 保留现有 `/w/{word}`、`/w/add`、`/api/words`、“今日复习”和本地学习体验。
