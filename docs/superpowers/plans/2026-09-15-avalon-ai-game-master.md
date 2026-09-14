# Avalon AI Game Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 独立完成并上线一个支持 5–12 名真人或 AI 玩家混合参与的阿瓦隆平台，用真实证据证明 React/TypeScript、FastAPI、PostgreSQL、实时通信、LLM Agent、评测、测试与部署能力。

**Architecture:** React 客户端只展示服务器确认的状态；FastAPI 承担 HTTP/WebSocket 边界，配置驱动的纯 Python 规则引擎是游戏状态转换的唯一权威，PostgreSQL 保存房间、玩家和不可变事件。AI GM 只能读取脱敏的公开状态；AI 玩家只接收与其角色相同的可见信息，并通过受限动作工具提交决定，所有动作仍由规则引擎校验。模型不可用时，GM 回退到确定性模板，AI 玩家按预设安全策略行动。

**Tech Stack:** React 19、TypeScript 5、Vite、TanStack Query、Vitest、Playwright；Python 3.12、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、pytest；PostgreSQL 16、WebSocket、Redis（多实例实时消息/后台任务阶段再引入）、Docker Compose、GitHub Actions、OpenTelemetry/Sentry、Render/Railway/Fly.io 中选择一个部署平台。

## Global Constraints

- 产品支持 5–12 人。`official` 规则集严格支持 5–10 人；11–12 人使用明确标注的 `extended` 自定义规则集，不把自定义平衡参数宣传为官方规则。
- 第一个可玩里程碑先完成 5 人基础局；随后用同一个 `RuleSet` 接口逐步开放 6–10 人官方配置和 11–12 人扩展配置，禁止按人数复制多套状态机。
- 规则、合法动作、阶段转换和胜负必须由确定性 Python 引擎决定；LLM 永远不能写入权威游戏状态。
- 第一版使用昵称和房间重连令牌，不做邮箱注册、OAuth、支付、好友系统和匹配系统。
- 每个功能切片都必须经历需求/验收标准、测试、实现、人工验证和一次清晰提交。
- 核心规则引擎测试分支覆盖率目标不低于 90%；仓库整体覆盖率目标不低于 75%。
- 任何密钥只从环境变量读取；仓库只提交 `.env.example`。
- 上线版本必须有 HTTPS、健康检查、结构化日志、CI 和一条可重复的部署路径。
- 简历只写实际测得的数据；目标值在达成前必须标注为 target，不能包装成结果。

## Scope, Difficulty, and Time

### 总体判断

| 版本 | 交付范围 | 难度 | 兼职时间（每周 12–15 小时） | 预计总工时 |
| --- | --- | ---: | ---: | ---: |
| M1 技术闭环 | 5 人、HTTP、单机房间、无 LLM | 5/10 | 4–5 周 | 55–75 小时 |
| M2 可公开 MVP | 5–10 人、实时联机、AI GM、部署 | 7.5/10 | 11–14 周累计 | 160–220 小时累计 |
| M3 简历旗舰版 | 5–12 人、AI 玩家、评测、观测、真人试玩 | 8.5/10 | 18–22 周累计 | 250–340 小时累计 |
| M4 进阶工程版 | 多实例扩展、Redis、负载/故障测试、多个 AI 策略 | 9/10 | 22–26 周累计 | 330–430 小时累计 |

推荐把 **M3** 当作简历完成线，M4 只在时间允许且 M3 已有真实用户后继续。最难的不是页面，而是隐藏信息隔离、并发动作一致性、断线恢复、AI 玩家合法且不越权、以及 11–12 人自定义规则的平衡证据。

### 模块难度与时间预算

| 模块 | 关键技能 | 难度 | 预计工时 | 主要风险 |
| --- | --- | ---: | ---: | --- |
| 需求、规则建模、ADR | 需求工程、状态机、领域建模 | 6/10 | 12–18h | 对官方规则和扩展规则边界表述错误 |
| 5–12 人规则引擎 | Python、类型、属性测试、配置设计 | 8/10 | 35–50h | 人数/角色/双失败任务产生组合爆炸 |
| API、数据库、事件回放 | FastAPI、SQL、事务、索引、并发控制 | 8/10 | 35–50h | 重复动作、并发写和回放不一致 |
| React 游戏客户端 | TS、组件、状态、请求、可访问性 | 7/10 | 40–55h | 阶段 UI 复杂、秘密数据误显示 |
| WebSocket 与重连 | async、协议、版本号、网络故障 | 8.5/10 | 30–45h | 乱序、重复消息、多标签页、掉线 |
| AI GM | LLM API、结构化输出、回退、成本 | 6.5/10 | 18–28h | 幻觉规则、超时、泄密 |
| AI 玩家 Agent | tool calling、记忆、策略、评测 | 9/10 | 45–70h | 非法动作、越权信息、行为不稳定、成本高 |
| Agent 评测 | 数据集、指标、人工标注、回归测试 | 8/10 | 25–40h | 只展示好案例，无法证明稳定性 |
| CI/CD、云与观测 | Docker、Linux、流水线、日志、追踪 | 8/10 | 30–45h | 环境差异、迁移失败、线上不可诊断 |
| 试玩与作品集包装 | UX 研究、指标、技术表达、英文 | 6/10 | 20–30h | 没有真实用户和可核验结果 |

### 5–12 人规则策略

- 5–10 人：使用出版方规则中的阵营人数、任务人数和“双失败任务”配置，测试数据注明规则来源。
- 11–12 人：定义为本项目的实验性扩展，使用 `RuleSet` 配置阵营比例、任务队伍人数、每任务失败阈值、可用角色和刺杀条件。
- 11–12 人初始参数不直接宣称平衡；先做蒙特卡洛基线模拟，再进行至少 20 局真人/AI 混合测试，比较正邪胜率、平均时长、任务通过率和刺杀成功率后再固定 `v1` 参数。
- 房主创建房间时清楚显示 `Official 5–10` 或 `Experimental 11–12`；扩展模式结果单独统计。

---

## 1. 训练目标与 AI 使用等级

这个项目不是“让 AI 替你做完”，而是让你在真实工程中建立可主动调用的能力。每次开始任务时，在 issue 或学习日志顶部写明本任务允许的 AI 等级。

| Level | AI 能做什么 | 你必须做什么 | 适用任务 |
| --- | --- | --- | --- |
| L0 无 AI | 不使用聊天、补全或生成 | 从空文件写核心逻辑，运行并解释结果 | Python/TS/SQL/Git 基础；每日 30 分钟；规则引擎关键函数 |
| L1 教练 | 解释概念、提问、给文档关键词；不提供最终代码 | 先口述设计，再关掉答案独立实现 | HTTP、事务、索引、React 状态、async/WebSocket 学习 |
| L2 审阅/排障 | 审查你已写的代码；按“现象→假设→最小实验”给提示 | 先独立尝试至少 25 分钟，带测试或报错求助，自己落修复 | Bug、重构、性能问题、测试遗漏 |
| L3 结对生产 | 生成明确规格下的样板、CSS、测试数据、迁移、配置、文档初稿 | 审查 diff、运行验证、能解释每个关键决定 | CRUD、UI 样式、Docker、CI、README |
| L4 受控 Agent | 在隔离分支完成一个有验收标准的小任务 | 先写规格和测试边界；逐文件 review；口头复盘；不懂的代码不合并 | 项目后半段的低风险独立切片 |

### 每周 AI 配额

- 每个工作日先做 30 分钟 L0；内容轮换为 Python、TypeScript、SQL、Git/调试。
- 每周至少一个核心切片用 L0/L1 完成，建议依次选择：规则状态转换、SQL 查询、React reducer、WebSocket 重连。
- L3/L4 生成的代码必须通过三道门：测试通过、你能画出数据流、你能解释一个失败模式。
- 每周复盘记录：独立完成内容、AI 帮助点、AI 错误、你如何发现、下周要脱离 AI 重做的一个知识点。

### AI 使用留证模板

```markdown
## Task reflection
- AI level: L1
- I wrote independently: `apply_action`, transition tests
- AI helped with: transaction isolation explanation
- AI was wrong about: allowing a second vote after the team was rejected
- Evidence I understand it: added failing regression test and explained the state diagram
- Retry without AI on: 2026-09-18
```

---

## 2. 文件结构

```text
GameMaster/
├─ apps/
│  ├─ api/
│  │  ├─ app/
│  │  │  ├─ api/rooms.py
│  │  │  ├─ api/games.py
│  │  │  ├─ api/ws.py
│  │  │  ├─ core/config.py
│  │  │  ├─ db/models.py
│  │  │  ├─ db/session.py
│  │  │  ├─ game/actions.py
│  │  │  ├─ game/engine.py
│  │  │  ├─ game/events.py
│  │  │  ├─ game/rulesets.py
│  │  │  ├─ game/state.py
│  │  │  ├─ game/views.py
│  │  │  ├─ agents/contracts.py
│  │  │  ├─ agents/player_agent.py
│  │  │  ├─ agents/policy_fallback.py
│  │  │  ├─ agents/memory.py
│  │  │  ├─ gm/client.py
│  │  │  ├─ gm/prompts.py
│  │  │  ├─ gm/service.py
│  │  │  └─ main.py
│  │  ├─ alembic/
│  │  ├─ tests/
│  │  └─ pyproject.toml
│  └─ web/
│     ├─ src/api/client.ts
│     ├─ src/features/lobby/
│     ├─ src/features/game/
│     ├─ src/features/gm/
│     ├─ src/lib/socket.ts
│     ├─ src/routes/
│     └─ package.json
├─ evals/
│  ├─ cases/gm_public_state.jsonl
│  ├─ cases/player_decisions.jsonl
│  └─ run_gm_evals.py
│  └─ run_player_evals.py
├─ docs/
│  ├─ architecture.md
│  ├─ decisions/
│  ├─ evidence/
│  └─ learning-log.md
├─ .github/workflows/ci.yml
├─ .env.example
├─ compose.yaml
└─ README.md
```

边界原则：`game/` 不导入 FastAPI、SQLAlchemy 或 LLM SDK；API 把请求转换为动作，规则引擎返回事件；数据库保存事件；客户端只消费公开/私有视图。

---

## 3. 18–22 周增量路线

每周按约 12–15 小时规划；课程高压周只完成该周最小可演示切片，不以赶进度牺牲课程通过。时间是累计区间，不要求机械地每七天切换任务；每个 milestone 必须先达到验收标准再进入下一阶段。

### Task 1（第 1 周，10–15h，难度 4/10）: 工程骨架与第一个纵向切片

**Files:**
- Create: `apps/api/app/main.py`
- Create: `apps/api/tests/test_health.py`
- Create: `apps/api/pyproject.toml`
- Create: `apps/web/src/App.tsx`
- Create: `apps/web/package.json`
- Create: `compose.yaml`
- Create: `.env.example`

**Interfaces:**
- Produces: `GET /health -> {"status": "ok"}`；浏览器页面显示 API 在线状态。

**AI level:** L0 完成 Git 初始化、分支、首次提交和健康检查；L3 可生成 Vite/CSS/Compose 样板。

- [ ] 写 `test_health_returns_ok`，断言状态码 200 和精确 JSON。
- [ ] 运行 `pytest apps/api/tests/test_health.py -q`，确认测试先因应用不存在而失败。
- [ ] 实现 FastAPI `GET /health`，只返回 `{"status": "ok"}`。
- [ ] 创建 React 页面，通过环境变量中的 API base URL 请求 `/health`，覆盖 loading、online、offline 三种状态。
- [ ] 添加前端测试，分别模拟成功与失败响应。
- [ ] 用 Compose 启动 web、api、postgres，浏览器验证前端确实访问容器中的 API。
- [ ] 提交 `chore: bootstrap full-stack health slice`。

**验收证据:** 一张浏览器截图、一段 20 秒启动录屏、CI 首次全绿截图。

### Task 2（第 2–4 周，35–50h，难度 8/10）: 配置驱动的 5–12 人阿瓦隆规则引擎

**Files:**
- Create: `apps/api/app/game/state.py`
- Create: `apps/api/app/game/actions.py`
- Create: `apps/api/app/game/events.py`
- Create: `apps/api/app/game/rulesets.py`
- Create: `apps/api/app/game/engine.py`
- Create: `apps/api/tests/game/test_engine.py`

**Interfaces:**
- Consumes: `Action` discriminated union。
- Produces: `apply_action(state: GameState, action: Action) -> tuple[GameState, list[GameEvent]]`。

**AI level:** 状态、动作类型和至少 8 个核心测试必须 L0；完成后可用 L2 查遗漏边界。

- [ ] 画出 `LOBBY → TEAM_PROPOSAL → TEAM_VOTE → MISSION_VOTE → ASSASSINATION → FINISHED` 状态图并写入 `docs/architecture.md`。
- [ ] 定义 `RuleSet`：`min_players/max_players/team_sizes/fail_thresholds/good_count/evil_count/roles/assassination_enabled`；引擎只能依赖该接口，不读取散落常量。
- [ ] 录入并逐项测试 5–10 人官方配置；为 11–12 人建立版本化 `extended_v0` 配置和“实验规则”元数据。
- [ ] 定义不可变 `GameState`、`PlayerState`、`MissionState` 和动作类型 `StartGame/ProposeTeam/VoteTeam/VoteMission/Assassinate`。
- [ ] 写失败测试：非房主不能开始、人数不等于 5 不能开始、队伍人数错误、非队长提名、重复投票、忠臣提交失败票、未入队玩家投任务票、第三次成功进入刺杀、三次失败邪恶方获胜。
- [ ] 实现角色洗牌，接受显式 RNG seed，使测试和回放可重复。
- [ ] 实现单一入口 `apply_action`；非法动作抛出带稳定错误码的 `RuleViolation`。
- [ ] 加入属性测试：任意动作序列都不能让成功/失败任务数超过 3，不能出现两个当前队长。
- [ ] 加入 5–12 人参数化测试：人数、角色数、任务队伍人数和失败阈值始终自洽；同一 seed 能完整重放。
- [ ] 运行规则引擎覆盖率并达到分支覆盖率 90%。
- [ ] 提交 `feat: add deterministic five-player avalon engine`。

**验收证据:** 终端对局回放、状态图、覆盖率报告；你能不看代码解释每个阶段和三个非法动作。

### Task 3（第 5–6 周，30–45h，难度 8/10）: PostgreSQL、迁移与事件回放

**Files:**
- Create: `apps/api/app/db/models.py`
- Create: `apps/api/app/db/session.py`
- Create: `apps/api/alembic/versions/0001_initial.py`
- Create: `apps/api/app/game/repository.py`
- Create: `apps/api/tests/integration/test_game_repository.py`

**Interfaces:**
- Produces: `GameRepository.append(game_id, expected_version, events)` 与 `GameRepository.load(game_id) -> GameState`。

**AI level:** L0 手写建表 SQL 草稿和 5 条 JOIN/GROUP BY 查询；L1 学事务与乐观并发；L3 可把确认后的 schema 转成 Alembic/SQLAlchemy 样板。

- [ ] 设计 `rooms`、`room_players`、`games`、`game_events`、`messages`，为事件增加 `(game_id, version)` 唯一约束。
- [ ] 写集成测试：追加事件后可回放为相同状态；旧 `expected_version` 写入会冲突；房间删除不会留下孤儿玩家。
- [ ] 实现单事务事件追加和乐观版本检查。
- [ ] 写并解释查询：房间玩家、对局时长、每局任务结果、玩家胜率、最近 20 个事件。
- [ ] 用真实 PostgreSQL 容器运行集成测试，不使用 SQLite 替代。
- [ ] 提交 `feat: persist and replay game events`。

**验收证据:** ER 图、迁移前后截图、事件重放一致性测试。

### Task 4（第 7 周，20–30h，难度 7.5/10）: HTTP API 与隐私视图

**Files:**
- Create: `apps/api/app/api/rooms.py`
- Create: `apps/api/app/api/games.py`
- Create: `apps/api/app/game/views.py`
- Create: `apps/api/tests/api/test_rooms.py`
- Create: `apps/api/tests/api/test_games.py`

**Interfaces:**
- Produces: `POST /rooms`、`POST /rooms/{code}/join`、`POST /games/{id}/actions`、`GET /games/{id}`。
- Produces: `build_player_view(state, player_id)`，只向本人返回其角色和合法可见信息。

**AI level:** L0 手写 Pydantic 请求/响应模型和一个 endpoint；其余 CRUD 可 L3，安全/隐私审查用 L2。

- [ ] 为四个 endpoint 先写成功、401/403、404、409 和 422 测试。
- [ ] 创建不可逆哈希的重连令牌；响应只返回一次原始令牌，数据库只存摘要。
- [ ] 实现 `build_player_view` 并测试忠臣看不到邪恶身份、梅林只看到规则允许的信息、公开响应永不包含所有角色映射。
- [ ] API 在一个数据库事务内加载状态、校验动作、追加事件，再返回新视图。
- [ ] 生成 OpenAPI 并人工用 API 文档完成一局关键路径。
- [ ] 提交 `feat: expose secure room and game APIs`。

**验收证据:** API 文档截图、隐私测试、一次完整 HTTP 对局记录。

### Task 5（第 8–10 周，40–55h，难度 7/10）: React 可玩界面

**Files:**
- Create: `apps/web/src/api/client.ts`
- Create: `apps/web/src/features/lobby/LobbyPage.tsx`
- Create: `apps/web/src/features/game/GamePage.tsx`
- Create: `apps/web/src/features/game/gameReducer.ts`
- Create: `apps/web/src/features/game/*.test.tsx`

**Interfaces:**
- Consumes: Task 4 HTTP API。
- Produces: 创建/加入房间、角色查看、组队、团队投票、任务投票、刺杀、结束页完整流程。

**AI level:** reducer、表单状态、async 请求和错误处理至少各一个 L0 实现；CSS 和可访问性初稿可 L3。

- [ ] 写组件测试：表单校验、按钮按合法动作启用、请求失败保留用户输入、重复提交被禁止、秘密角色不能出现在公共 DOM。
- [ ] 实现 lobby 创建/加入流程，将重连令牌保存在 session storage。
- [ ] 用 reducer 表达 UI 状态，不在多个组件复制服务器状态。
- [ ] 为每个阶段实现单一主操作区，并显示服务器返回的合法动作。
- [ ] 添加键盘焦点、label、颜色之外的成功/失败标识和窄屏布局。
- [ ] 用五个独立浏览器上下文手工完成一局。
- [ ] 提交 `feat: add playable avalon web client`。

**验收证据:** 60–90 秒无剪辑对局 Demo、移动端和桌面截图、组件测试报告。

### Task 6（第 11–12 周，30–45h，难度 8.5/10）: WebSocket 实时同步与断线恢复

**Files:**
- Create: `apps/api/app/api/ws.py`
- Create: `apps/api/app/realtime/hub.py`
- Create: `apps/api/tests/realtime/test_ws.py`
- Create: `apps/web/src/lib/socket.ts`
- Create: `apps/web/src/lib/socket.test.ts`

**Interfaces:**
- Produces: `WS /ws/rooms/{code}?token=...`，消息 envelope 为 `{type, gameId, version, payload}`。

**AI level:** L1 学习连接生命周期；第一次重连状态机 L0；完成后用 L2 做竞态审查。

- [ ] 写测试：无效令牌拒绝、动作后所有在线玩家收到各自脱敏视图、断线重连从最新 version 恢复、重复/旧 version 消息被客户端忽略。
- [ ] 实现连接注册、离开和按玩家发送个性化状态，禁止广播包含秘密角色的统一对象。
- [ ] 客户端实现指数退避重连，上限 10 秒；重连成功后主动拉取服务器快照。
- [ ] 加入连接状态提示，但断线期间禁止提交游戏动作。
- [ ] 使用 Playwright 五浏览器测试完成“玩家掉线—其他人继续—玩家回来看到最新状态”。
- [ ] 提交 `feat: synchronize games over websocket`。

**验收证据:** 断网/恢复录屏、WebSocket 集成测试、竞态复盘笔记。

### Task 7（第 13 周，18–28h，难度 6.5/10）: AI GM、工具边界与安全回退

**Files:**
- Create: `apps/api/app/gm/client.py`
- Create: `apps/api/app/gm/prompts.py`
- Create: `apps/api/app/gm/service.py`
- Create: `apps/api/tests/gm/test_service.py`
- Create: `apps/web/src/features/gm/GmPanel.tsx`

**Interfaces:**
- Consumes: `PublicGameView` 和已发生的公开事件。
- Produces: `Narration {event_id, text, model, latency_ms, fallback_used}`。
- Tools: `get_public_state()`、`explain_rule(topic)`、`narrate_event(event_type)`；这些工具均无状态写权限。

**AI level:** L1 自己设计 prompt 边界与威胁模型；SDK 接入可 L3；泄密测试和 fallback 必须自己 review。

- [ ] 写威胁模型：秘密身份泄露、prompt injection、模型幻觉规则、超时、费用失控、重复旁白。
- [ ] 先实现确定性中文/英文主持模板，保证没有模型也能完成整局。
- [ ] 写测试：传给模型的对象不含秘密角色；输出不能改变阶段；超时 3 秒走模板；同一 `event_id` 不重复计费生成。
- [ ] 接入结构化输出，只允许 `tone`、`announcement`、`rule_hint` 字段；解析失败走模板。
- [ ] 记录 provider、model、token、latency、success/fallback，不记录玩家秘密和完整 prompt。
- [ ] UI 将 AI 文本明确标记为主持旁白，并允许房主关闭 AI。
- [ ] 提交 `feat: add bounded ai game master narration`。

**验收证据:** 模型开启/关闭对比、故障回退 Demo、无秘密字段的请求样例、成本统计。

### Task 8（第 14 周，18–25h，难度 7/10）: AI GM 评测与可观测性

**Files:**
- Create: `evals/cases/gm_public_state.jsonl`
- Create: `evals/run_gm_evals.py`
- Create: `apps/api/app/core/logging.py`
- Create: `apps/api/tests/test_observability.py`

**Interfaces:**
- Produces: `evals/results/latest.json`，字段为 `case_id/parse_ok/secret_leak/rule_error/fallback/latency_ms`。

**AI level:** 测试用例与评分规则 L0/L1；生成额外措辞变体可 L3；最终失败样例必须人工复核。

- [ ] 人工编写至少 30 个评测案例，覆盖每个阶段、中文/英文、诱导泄密、要求 AI 篡改结果和未知规则问题。
- [ ] 实现确定性检查：JSON 可解析、无禁止秘密词、事件类型一致、输出长度和延迟在阈值内。
- [ ] 为“规则事实是否正确”维护人工标注字段，不让另一个 LLM 成为唯一裁判。
- [ ] 添加 request/game/event correlation ID 和 JSON 日志；健康检查区分进程存活与数据库就绪。
- [ ] 在 README 发布实际评测数字和失败案例，不隐藏限制。
- [ ] 提交 `test: add gm evaluations and structured observability`。

**验收证据:** 评测结果表、一次模型失败的日志链路、你对失败原因的书面分析。

### Task 9（第 15–16 周，30–45h，难度 8/10）: CI/CD、云部署与运行手册

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `apps/api/Dockerfile`
- Create: `apps/web/Dockerfile`
- Create: `docs/runbook.md`
- Modify: `compose.yaml`

**Interfaces:**
- Produces: PR 执行 lint/typecheck/unit/integration/e2e/build；主分支通过后部署 staging/production。

**AI level:** 先用 L1 解释每个构建步骤；配置可 L3；你必须 L0 完成一次服务器日志定位、环境变量设置和回滚演练。

- [ ] CI 使用固定版本，依次执行 Python lint/typecheck/test、前端 lint/typecheck/test、PostgreSQL 集成测试、Playwright 冒烟和镜像 build。
- [ ] Docker 镜像使用非 root 用户并配置 healthcheck；前端构建时不嵌入服务端密钥。
- [ ] 在选定平台创建 PostgreSQL、API、web 服务，配置 HTTPS 和允许来源。
- [ ] 从空数据库运行迁移并完成一次线上五人关键路径。
- [ ] 写运行手册：部署、迁移、查看日志、轮换密钥、回滚上一个镜像、恢复数据库备份。
- [ ] 人为部署一个坏健康检查到 staging，验证平台阻止或回滚，再保留证据。
- [ ] 提交 `ci: deploy tested game master release`。

**验收证据:** 公开 URL、绿色流水线、部署/回滚记录、线上健康检查。

### Task 10（第 17 周，18–25h，难度 8/10）: AI 玩家契约、信息隔离与安全策略

**Files:**
- Create: `apps/api/app/agents/contracts.py`
- Create: `apps/api/app/agents/policy_fallback.py`
- Create: `apps/api/tests/agents/test_contracts.py`
- Create: `apps/api/tests/agents/test_information_boundary.py`

**Interfaces:**
- Consumes: `build_player_view(state, player_id)` 和服务器返回的 `legal_actions`。
- Produces: `AgentObservation`、`AgentDecision`；工具严格限定为 `propose_team`、`vote_team`、`vote_mission`、`assassinate`。

**AI level:** Agent 数据契约、信息流图和秘密泄露测试必须 L0/L1；Pydantic 样板可 L3。

- [ ] 定义每种角色可见信息矩阵，并为 Merlin、Percival、Mordred、Morgana、Oberon、Assassin 和普通阵营角色写测试。
- [ ] 从玩家视图生成 `AgentObservation`，只包含该玩家可见信息、公开事件摘要和当前合法动作，不传数据库模型或全局状态。
- [ ] 定义结构化 `AgentDecision`，所有 player id 必须来自 `legal_actions`，所有动作带 `game_id/player_id/expected_version/reasoning_summary`。
- [ ] 实现不依赖模型的 fallback policy：随机但合法地选择动作；使用显式 seed 以便回归测试。
- [ ] 写越权测试：恶意 prompt 要求查看全部角色、修改票数、跳过阶段或冒充其他玩家时，Agent 仍无法获得相应数据/权限。
- [ ] 在规则引擎入口再次验证 Agent 动作，证明“提示词不是安全边界”。
- [ ] 提交 `feat: define safe ai player action boundary`。

**验收证据:** 角色可见信息矩阵、越权测试、fallback AI 完成整局的可重复日志。

### Task 11（第 18–19 周，30–45h，难度 9/10）: LLM AI 玩家、短期记忆与混合房间

**Files:**
- Create: `apps/api/app/agents/player_agent.py`
- Create: `apps/api/app/agents/memory.py`
- Create: `apps/api/tests/agents/test_player_agent.py`
- Create: `apps/api/app/jobs/agent_turns.py`
- Modify: `apps/web/src/features/lobby/LobbyPage.tsx`
- Modify: `apps/web/src/features/game/GamePage.tsx`

**Interfaces:**
- Produces: `PlayerAgent.decide(observation: AgentObservation) -> AgentDecision`。
- Produces: 房主可添加/移除 AI 席位并选择 `baseline/cautious/aggressive` 行为配置。

**AI level:** 工具 schema 与 orchestrator 可 L2/L3；你必须独立解释 async、超时、幂等、版本冲突、token 预算和记忆裁剪。

- [ ] 先接入一个模型供应商，通过结构化 tool calling 返回单个动作；Agent 不能直接访问 repository。
- [ ] 为每个回合设置 8 秒超时、一次结构化重试和每局 token/cost 上限；失败后执行 fallback policy。
- [ ] 记忆只保存公开陈述、投票、任务结果和该角色自己的推断；每回合生成定长摘要，禁止写入未知秘密身份。
- [ ] Agent 动作进入与真人相同的 command path，使用 `expected_version`；发生并发冲突时重新读取一次状态，不能盲目重放旧决定。
- [ ] 在后台任务中调度 AI 回合，API 请求不等待模型完成；连续 AI 玩家之间设置可配置节奏。
- [ ] UI 显示 AI 席位、思考/回退状态和简短公开发言；不得展示隐藏 chain-of-thought。
- [ ] 写混合 E2E：3 真人 + 2 AI、1 真人 + 4 AI、12 席位含多个 AI，均可完成整局且不出现非法状态。
- [ ] 提交 `feat: let bounded ai agents join player seats`。

**验收证据:** 真人/AI 混合整局 Demo、超时回退、并发冲突恢复、每局成本记录。

### Task 12（第 20 周，25–40h，难度 8/10）: AI 玩家评测与 11–12 人平衡实验

**Files:**
- Create: `evals/cases/player_decisions.jsonl`
- Create: `evals/run_player_evals.py`
- Create: `evals/simulate_rulesets.py`
- Create: `docs/evidence/agent-evaluation.md`
- Create: `docs/evidence/extended-rules-balance.md`

**Interfaces:**
- Produces: 每次模型/提示词/规则修改都可重复运行的离线决策评测与完整对局模拟报告。

**AI level:** 指标选择和人工金标必须 L0/L1；批量生成场景可 L3，但需去重和人工审核。

- [ ] 建立至少 80 个决策案例，覆盖不同人数、阵营、角色、阶段、合法动作数量、诱导越权和版本冲突。
- [ ] 测量合法动作率、越权信息率、结构化输出率、超时率、fallback 率、P50/P95 延迟和平均每局成本。
- [ ] 用 deterministic baseline、random legal baseline 和 LLM Agent 做对比，禁止只展示 LLM 的成功案例。
- [ ] 对 11–12 人 `extended_v0` 进行至少 10,000 局无 LLM 蒙特卡洛模拟，先排除明显不合理的阵营/任务参数。
- [ ] 完成至少 20 局 11–12 人真人或真人/AI 混合试玩；记录正邪胜率、平均时长、中途退出和主观平衡反馈。
- [ ] 根据证据发布 `extended_v1`；保留 v0 配置和变更说明，使结果可复现。
- [ ] 将评测作为可手动触发的 CI job，模型或 prompt 版本更新前后保存对比结果。
- [ ] 提交 `eval: benchmark ai players and extended rules`。

**验收证据:** 基线对比表、失败样例、10,000 局模拟报告、20 局扩展玩法数据。

### Task 13（第 21–22 周，20–30h，难度 6/10）: 作品集发布与面试材料

**Files:**
- Create: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/decisions/0001-deterministic-engine.md`
- Create: `docs/decisions/0002-event-log.md`
- Create: `docs/evidence/resume-metrics.md`
- Create: `docs/learning-log.md`

**Interfaces:**
- Produces: 招聘者可在 3 分钟内理解价值、架构、你的贡献、工程质量和在线 Demo。

**AI level:** README 排版和英文润色可 L3；架构讲解、取舍、指标来源和面试口述必须由你先写。

- [ ] README 首屏写清：用户问题、在线 Demo、60–90 秒视频、架构图、技术栈、快速启动。
- [ ] 展示浏览器 → React → HTTP/WebSocket → FastAPI → 规则引擎 → PostgreSQL/LLM Agent 的数据流，以及 AI 玩家与真人共用 command path 的安全边界。
- [ ] 至少写四篇 ADR：LLM 不拥有规则、事件日志用于回放/并发控制、5–10 官方/11–12 扩展规则分离、AI Agent 最小权限与 fallback。
- [ ] 记录实际数据：测试数量/覆盖率、CI 时长、评测通过率、P95 API/AI 延迟、回退率、试玩人数和反馈数量。
- [ ] 邀请至少 10 名真实试玩者，收集 3 个固定问题：哪里卡住、哪里不信任 AI、是否愿意再玩。
- [ ] 录制无剪辑 Demo，打 `v1.0.0` tag，发布 release notes。
- [ ] 准备 2 分钟中文和英文项目介绍，以及 5 个 STAR/深挖问题答案。
- [ ] 对照至少 5 个目标岗位 JD，把 README 和简历项目描述调整到 Full-stack / Backend / AI Application 的共同技能证据，不能虚构岗位关键词对应能力。
- [ ] 提交 `docs: publish portfolio-ready v1 release`。

**验收证据:** 公开仓库、release、Demo、试玩反馈、指标来源表。

---

## 4. 每周工作节奏

```text
周一：写本周 user story、验收标准、状态图/接口草图
周二：L0/L1 核心实现 + 失败测试
周三：完成纵向切片并本地演示
周四：集成测试、排障、AI review
周五：部署到 staging、整理证据、写学习复盘
周末：找真人试玩或补课程；不无边界扩需求
```

每次工作结束必须留下至少一个外部可见结果：测试、提交、截图、可访问页面、评测结果或复盘。只“看教程”不计入项目进度。

## 5. Definition of Done

一个切片只有同时满足以下条件才算完成：

- 用户路径可运行，不依赖开发者手工改数据库。
- 正常路径和至少一个失败路径有自动测试。
- 格式检查、类型检查、测试和构建全部通过。
- 不含密钥、私人数据、缓存和构建垃圾。
- README/架构图与当前实现一致。
- 你能在不看 AI 答案的情况下解释数据流、关键取舍和一个失败模式。
- 已保存可核验的截图、视频、日志或指标。

## 6. 项目所训练和证明的技能

| 技能方向 | 项目中的具体练习 | 面试/简历证据 |
| --- | --- | --- |
| Python | 状态机、类型、异常、async、领域模型 | 纯规则引擎、属性测试、并发冲突处理 |
| TypeScript/React | 类型、组件、表单、状态、Query、WebSocket | 5–12 人完整交互、断线恢复、组件/E2E 测试 |
| SQL/PostgreSQL | 建模、JOIN、索引、事务、迁移 | ER 图、查询、事件回放、执行计划和一致性测试 |
| API/网络 | REST、HTTP 状态码、鉴权、幂等、WebSocket | OpenAPI、协议文档、消息版本和失败重试 |
| 软件工程 | Git 分支、TDD、ADR、CI、review、release | 清晰提交、绿色 CI、架构决策、版本发布 |
| 云与运维 | Linux、Docker、环境变量、HTTPS、回滚 | 公开 URL、运行手册、线上故障演练 |
| AI Application | structured output、tool calling、memory、fallback | GM 和玩家 Agent、成本/延迟/失败指标 |
| Agent 安全/评测 | 最小权限、信息隔离、基线、回归评测 | 泄密测试、80+ 案例、baseline 对比 |
| 产品能力 | 范围控制、可用性、试玩反馈、指标 | 10+ 用户、问题记录和迭代前后证据 |
| 技术表达 | README、架构图、中文/英文讲解 | 公开文档、Demo、2 分钟项目介绍 |

## 7. 可用于简历的表述骨架（完成后填真实数据）

```text
Avalon AI Game Master｜独立全栈与 Agent 工程项目
- 设计并上线 React/TypeScript + FastAPI + PostgreSQL 的 5–12 人实时社交推理平台，以配置驱动状态机、事件日志和乐观并发控制处理组队、投票、任务、刺杀及断线回放。
- 构建最小权限 AI GM 与 AI 玩家 Agent，通过结构化工具调用参与真人混合对局，并以信息隔离、超时回退、成本限制和离线评测控制模型风险。
- 建立覆盖单元、属性、PostgreSQL 集成、WebSocket 和 Playwright E2E 的 CI/CD；以实际覆盖率、Agent 合法动作率、P95 延迟、每局成本及真实试玩人数验证质量。
```

在 `N/X` 产生真实数据前，不把这段直接复制进简历。

## 8. 自检结果

- 需求覆盖：前端、后端、数据库、实时同步、AI Agent、评测、测试、部署、作品集证据均有独立增量。
- 范围控制：M2 不含账号系统、匹配、语音和多个游戏；AI 玩家在 M2 上线后进入 M3，不反向阻塞真人核心玩法。
- 隐私边界：服务端为每位玩家生成独立视图；AI GM 只读公开状态，AI 玩家只读与其座位身份相符的信息。
- 类型一致：所有动作经 `apply_action`，所有持久化经 `GameRepository.append/load`，客户端以 `version` 处理实时消息。
- 训练一致：规则、基础 TS/Python/SQL/Git 保持 L0/L1；样板和文档允许更高等级 AI，但合并前必须可解释和验证。
