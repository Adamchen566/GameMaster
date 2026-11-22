# 迭代路线（2026-11-22 修订）

> 本文件决定**做什么、按什么顺序做**。每个 Task 的详细步骤、接口和 AI 等级规则仍看
> [`superpowers/plans/2026-09-15-avalon-ai-game-master.md`](superpowers/plans/2026-09-15-avalon-ai-game-master.md)
> 和 [`getting-started.md`](getting-started.md)。顺序或范围冲突时以本文件为准。
>
> 本文件里的工时和日期全部是 **target**，不是结果。

## 1. 现状快照（2026-11-22）

| 项 | 状态 | 位置 |
| --- | --- | --- |
| 仓库骨架、`.gitignore`、`.editorconfig`、计划文档 | 完成 | `main` |
| 后端 `GET /health` + 1 个 pytest | 完成 | `main` |
| 前端状态页（connecting / online / offline）+ 3 个 Vitest | 写完未合并 | 分支 `codex/frontend-health-status`，无 PR |
| `compose.yaml`、`.env.example`、CI | 未开始 | — |
| 学习日志 Entry 001 / 002 | 模板在，本人填写部分为空 | `docs/learning-log.md` |
| Task 2–13 | 未开始 | — |

- 三次提交都在 2026-09-15，之后到本次修订没有新提交。
- 前端 3 个测试通过的说法来自学习日志，本次修订没有重跑。
- 这张表是修订当天的基线，之后的进度看第 4 节的勾选。

## 2. 相对原计划的调整

| 调整 | 原计划 | 现在 | 原因 |
| --- | --- | --- | --- |
| 先可玩 | 引擎 → 数据库 → API → 界面，第 10 周才能玩一局 | 引擎 → 内存仓库 + API + 界面，数据库后移 | 原计划 M1 写 4–5 周出技术闭环，任务顺序却要 10 周 |
| bot 提前 | 随机合法 bot 在 Task 10（第 17 周） | 紧跟规则引擎 | 一个人就能打完整局，不用开五个浏览器；也是后面 LLM 玩家的回退策略 |
| 联机暂缓 | Task 6 WebSocket 在第 11–12 周 | 不排期，见第 5 节 | 先把单人对 AI 的完整闭环做到上线 |
| 11–12 人扩展规则暂缓 | Task 2 / Task 12 含 `extended_v0`、10,000 局模拟、20 局真人试玩 | 只做官方 5–10 人 | 12 人真人局凑不齐，证据拿不到 |

不变的部分：确定性规则引擎是唯一权威、LLM 不写游戏状态、按玩家生成脱敏视图、AI 五等级和学习日志规则。

## 3. 版本路线

| 版本 | 交付 | 对应原 Task | 工时 target | AI 等级 |
| --- | --- | --- | --- | --- |
| v0.1 骨架收尾 | 合并前端、清理、compose、`.env.example`、CI | 1 | 6–8h | L3 |
| v0.2 规则引擎 | 5–10 人 `RuleSet`、状态机、属性测试 | 2 | 35–50h | L4，本人逐文件 review |
| v0.3 单人可玩 | 隐私视图 + 随机合法 bot + 内存仓库 + HTTP API + 最小界面 | 4、10 前半、5 精简 | 45–60h | L4，本人逐文件 review |
| v0.4 持久化 | PostgreSQL 事件日志、乐观并发、回放 | 3 | 30–45h | L4，本人逐文件 review |
| v0.5 上线 | Docker、完整 CI、云部署、运行手册 | 9 | 25–35h | L1 + L3，回滚演练 L0 |
| v0.6 AI | AI GM 旁白 + LLM 玩家 | 7、10 后半、11 | 45–70h | L1–L3 |
| v0.7 评测 | GM 30 例、玩家 80 例、基线对比、结构化日志 | 8、12（去掉 11–12 人） | 30–45h | 指标和金标 L0/L1 |
| v0.8 圆桌与发言 | 发言阶段、会推理的机器人、圆桌界面 | 试玩反馈 | — | L4，本人试玩 |
| v1.0 作品集 | README、架构图、ADR、Demo、试玩反馈 | 13 | 20–30h | 讲解本人先写 |

合计约 235–345h。

## 4. 各版本的交付与验收

### v0.1 骨架收尾

- [x] 把 `codex/frontend-health-status` 合并到 `main`。
- [x] 删除已入库的 `apps/web/tsconfig.*.tsbuildinfo`，并加入 `.gitignore`。
- [x] `vite`、`@vitejs/plugin-react` 移到 `devDependencies`。
- [x] API 地址改为从环境变量读取（原计划要求）：浏览器侧 `VITE_API_BASE_URL`，代理目标 `API_PROXY_TARGET`；去掉 8000 端口文案。
- [x] 添加 `compose.yaml`（web、api、postgres）、两个开发用 Dockerfile 和 `.env.example`。
- [x] 添加 `.github/workflows/ci.yml`：后端 ruff + pytest，前端 typecheck + vitest + build，外加 Compose 冒烟测试。
- [x] README 与现状一致。

**验收：** CI 全绿，其中 Compose 冒烟测试确认三个服务健康、前端代理能访问到后端。

### v0.2 规则引擎

按原 Task 2 执行，范围收窄为官方 5–10 人。2026-11-22 调整：实现由 AI 完成（L4），本人负责逐文件 review；原计划里“规则引擎必须 L0”的要求已取消。设计说明见 [`architecture.md`](architecture.md)。

- [x] 状态图写入 `docs/architecture.md`。
- [x] `RuleSet` 接口 + 5–10 人官方配置，逐项测试并注明规则来源。
- [x] 不可变 `GameState` / `PlayerState` / `MissionState`，动作类型 `StartGame / ProposeTeam / VoteTeam / VoteMission / Assassinate`。
- [x] 单一入口 `apply_action`；非法动作抛带稳定错误码的 `RuleViolation`。
- [x] 显式 RNG seed 的角色洗牌。
- [x] 属性测试 + 5–10 人参数化测试。
- [x] 事件驱动：状态只经 `evolve(state, event)` 改变，`replay` 可由事件重建状态（为 v0.4 的事件日志准备）。
- [x] 终端模拟器 `python -m app.game.simulate`。
- [x] CI 检查规则引擎分支覆盖率 ≥ 90%（当前 100%）。
- [ ] 本人逐文件 review，并能不看代码讲清每个阶段和三个非法动作。

**验收：** 规则引擎分支覆盖率 ≥ 90%；同一 seed 的终端对局可完整重放；能不看代码讲清每个阶段和三个非法动作。

### v0.3 单人可玩

目标是 1 名真人 + bot 补满席位，在浏览器里打完一局。2026-11-22 调整：与 v0.2 一样由 AI 实现（L4），本人逐文件 review；原计划里“第一个 reducer 和一个 endpoint 必须 L0”的要求已取消。

- [x] `game/views.py`：`build_player_view(state, player_id)`，秘密信息的唯一出口。
- [x] `agents/policy_fallback.py`：随机但合法的 bot，显式 seed。
- [x] `GameRepository` 接口（`append(game_id, expected_version, events)` / `load(game_id)`）+ 内存实现。
- [x] HTTP：`POST /rooms`（创建并用 bot 补满席位）、`POST /games/{id}/actions`、`GET /games/{id}`。
- [x] 重连令牌：只返回一次原文，服务端只存摘要；前端放 session storage。
- [x] 真人提交动作后，服务器在同一请求内推进 bot 回合，直到轮到真人或对局结束。
- [x] 界面：创建对局、查看角色、组队、团队投票、任务投票、刺杀、结束页；用 reducer 表达 UI 状态，只展示服务器返回的 `legalActions`。
- [x] 隐私测试：忠臣看不到邪恶身份、梅林只看到规则允许的信息、公开响应不含全角色映射、秘密角色不进公共 DOM。

- [x] 界面采用“琥珀夜色”设计系统；在浏览器里实际打完一局，刷新后能回到对局。
- [ ] 本人逐文件 review，并在本机亲手玩一局。

**验收：** 1 真人 + 4 bot 完成一局的无剪辑录屏；全 bot 对局同 seed 可重放；每个 endpoint 有成功和 403 / 404 / 409 / 422 测试。

**顺带产出（可选）：** 全 bot 批量模拟脚本，得到 5–10 人随机策略的正邪胜率基线，v0.7 直接复用。

### v0.4 持久化

按原 Task 3 执行，把内存仓库换成 PostgreSQL 实现，接口不变。2026-11-22 调整：与 v0.2、v0.3 一样由 AI 实现（L4），本人逐文件 review；原计划的“L0 SQL、L1 事务”和“手写 5 条查询”改为读懂并能讲清。表结构和查询说明见 [`database.md`](database.md)。

- [x] 表：`rooms`、`room_players`、`games`、`game_events`；`(game_id, version)` 唯一约束（事件表主键）。
- [x] Alembic 初始迁移；测试检查迁移结果与代码里的表定义一致。
- [x] 单事务事件追加 + 乐观版本检查；建房的三张表同一事务。
- [x] 集成测试跑真实 PostgreSQL 容器（CI）：回放一致、旧 `expected_version` 冲突、并发写入只成功一个、无孤儿玩家。
- [x] 5 条查询及说明：房间玩家、对局时长、每局任务结果、玩家胜率、最近 20 个事件；CI 在 PostgreSQL 上执行并核对结果。
- [x] API 和 Compose 接入 `DATABASE_URL`；没有它时仍用内存，本机也可用 SQLite 文件。
- [x] Compose 冒烟测试：开一局 → 重启 API 容器 → 同一令牌取回同一局。
- [ ] 本人逐文件 review，能讲清乐观并发的那条 `UPDATE` 和 5 条查询各自走哪个索引。

**验收：** 服务重启后刷新页面能回到同一局；ER 图；回放一致性测试。

### v0.5 上线（2026-11-22 暂时跳过）

按原 Task 9 执行。本人决定先跳过上线、继续开发 v0.6；下面的条目保留，回头再做。

- [ ] CI 补齐：Playwright 单浏览器冒烟（1 真人 + bot 一局）、镜像 build。
- [ ] 两个 Dockerfile：非 root 用户 + healthcheck；前端构建不嵌入服务端密钥。
- [ ] 选定一个平台（Render / Railway / Fly.io），配置 PostgreSQL、API、web、HTTPS、允许来源。
- [ ] 健康检查区分进程存活与数据库就绪。
- [ ] `docs/runbook.md`：部署、迁移、看日志、轮换密钥、回滚、恢复备份。
- [ ] 回滚演练一次并留证。

**验收：** 公开 URL 上从空数据库完成 1 真人 + 4 bot 一局；绿色流水线；回滚记录。

### v0.6 AI

合并原 Task 7、Task 10 后半和 Task 11。

分两部分交付。第一部分是不依赖对局接入的核心模块，全部用脚本化的假模型测试；第二部分把它们接进服务和界面。与前几个版本一样由 AI 实现（L4），本人逐文件 review。

**第一部分：核心模块**

- [x] 威胁模型：秘密泄露、prompt injection、幻觉规则、超时、费用失控（[`threat-model.md`](threat-model.md)）。
- [x] AI GM：确定性中英文模板先行；结构化输出只允许 `tone / announcement / rule_hint`；3 秒超时或解析失败走模板；同一 `event_id` 不重复生成。`rule_hint` 是固定集合里的键，规则文字由模板给出。
- [x] 角色可见信息矩阵（Merlin、Percival、Mordred、Morgana、Oberon、Assassin、普通角色）及测试，在视图层和发给模型的观察层各一份。
- [x] `AgentObservation` / `AgentDecision` 契约；player id 必须来自 `legal_actions`。
- [x] `public_log`：事件日志的公开投影，AI 主持和玩家记忆的唯一来源。
- [x] LLM 玩家：单动作结构化输出；8 秒超时 + 一次结构化重试；每局 token / cost 上限；失败回退到 v0.3 的 bot。（原计划写的是强制 tool calling；默认模型 Claude Opus 5.5 不支持强制指定工具，改用结构化输出，效果相同。）
- [x] Claude 适配器（官方 `anthropic` SDK）；只对着假的 SDK 客户端测过，**没有用真实密钥发过请求**。
- [x] 越权测试：恶意 prompt 要求看全部角色、改票、跳阶段、冒充他人，均拿不到数据或权限。

**第二部分：接入对局**

- [x] 记忆落库：每个 AI 席位的笔记（最多 400 字）和上一回合的结果存进 `agent_states` 表；公开日志每回合从事件重新投影（最近 30 条）。
- [x] AI 回合改为后台任务，API 请求不等模型；前端轮询 `GET /games/{id}` 显示思考 / 回退状态。服务重启后，下一次轮询会重新启动没走完的 AI 回合。
- [x] 房主可选择 bot / LLM 席位数和 `baseline / cautious / aggressive` 打法，主持人可选固定播报 / AI 主持 / 关闭。服务器没配置模型时这些选项不出现。
- [x] 每局 token 用量和估算成本随 `GET /games/{id}` 返回（`ai_usage`）。
- [x] 在浏览器里用**脚本化的假模型**走通：AI 席位徽标、思考中、自动刷新、主持播报。
- [ ] 用真实密钥跑通一局，记录每局成本。（需要本人提供 `ANTHROPIC_API_KEY`，会产生费用。）
- [ ] 本人逐文件 review。

已知限制：同一时刻多个 AI 席位要行动时（例如组队投票）是一个一个问模型的，不是并行；AI 主持的文字和 token 预算只存在内存里，重启后旧事件回到固定播报、预算重新计数。

**验收：** 1 真人 + 4 LLM 玩家完成一局的 Demo；模型开 / 关对比；超时回退录屏；每局成本记录。

### v0.7 评测

合并原 Task 8 和 Task 12，去掉 11–12 人平衡实验。

与前几个版本一样由 AI 实现（L4），本人逐文件 review；原计划的“指标选择和人工金标 L0/L1”改为读懂并能讲清。说明和数字见 [`evidence/agent-evaluation.md`](evidence/agent-evaluation.md)。

- [x] GM 评测 32 例：每种公开事件、中英文、诱导泄密、要求篡改结果、未知规则问题。
- [x] 玩家决策评测 109 例：5–10 人、四种角色、四个阶段、4 种诱导越权；其中 29 例有无争议的唯一正解。
- [x] 指标：最终动作合法率、首答合法率、越权率、越权信息率、结构化输出率、超时率、fallback 率、P50 / P95 延迟、token 与成本。
- [x] 评测运行器 `python -m app.evals.run`：不花钱的两个替身模型（合法 / 捣乱）用来自检管线和防线；安全不变量被打破时退出码为 1。
- [x] 基线：随机 bot 对随机 bot 每种人数 2000 局的胜率和 95% 区间；整局对比（模型当好人 / 当邪恶，对随机 bot）的运行器。
- [x] “主持的话是否与事实一致”保留人工标注：每次运行生成 `gm_labels.csv`，不让另一个 LLM 当裁判。
- [x] request / game / event correlation ID + JSON 日志（`X-Request-ID`、`game_id`、`event_id = game_id:version`）；日志不含令牌、角色、任务牌、笔记。
- [x] 评测做成可手动触发的 CI job（Actions → Evals）。
- [x] 评测发现并修复：AI 主持在对局中可以“指控”某人是某角色；现在出现角色名的模型文字一律丢弃。
- [ ] 用真实密钥跑评测，填上 Claude 的数字和失败样例。（需要本人提供 `ANTHROPIC_API_KEY`，会产生费用。）
- [ ] 人工标注一轮 `gm_labels.csv`。（要先有真实模型的输出。）
- [ ] 本人逐文件 review。

**验收：** 基线对比表、失败样例和书面分析；README 发布实际数字。目前随机基线和替身模型的数字已发布，Claude 一栏为空。

### v0.8 圆桌与发言（2026-11-22 追加）

本人试玩后的反馈：页面不是圆桌；游戏的核心是发言对弈，而机器人在随机行动。这一版据此改。说明见 [`architecture.md`](architecture.md) 第 3、7 节。

- [x] 规则引擎加入 `DISCUSSION` 阶段：队长提出队伍后，从队长开始按座位每人发言一次，再投票；发言和点名进事件日志和公开记录。
- [x] 会推理、会发言的机器人 `table_bot` 取代随机 bot 补位：按公开证据算每个人是坏人的概率，说出理由，说和做一致。
- [x] 模型席位在轮到时由模型发言；别人的发言作为公开记录给它看。
- [x] 界面改成圆桌：座位围成一圈，中间是 1–5 号任务卡（成功 / 失败 / 未做），座位上方是发言气泡。
- [x] 在浏览器里用新界面打完一局。
- [x] 评测用例随新阶段重新生成（玩家 141 例），基线加入“机器人对机器人”。
- [ ] 机器人读不懂自由文本，只对“点名”有反应；要让发言的文字起作用，需要模型席位（要密钥）。
- [ ] 发言是一次性全部出现的，没有逐个播放的节奏。
- [ ] 本人试玩并反馈。

### v1.0 作品集

按原 Task 13 执行。

- [ ] README 首屏：用户问题、在线 Demo、60–90 秒视频、架构图、技术栈、快速启动。
- [ ] `docs/architecture.md` 数据流图。
- [ ] 至少三篇 ADR：LLM 不拥有规则、事件日志用于回放和并发控制、AI Agent 最小权限与回退。
- [ ] `docs/evidence/resume-metrics.md`：测试数 / 覆盖率、CI 时长、评测通过率、P95 延迟、回退率、试玩人数。
- [ ] 5–10 名真实试玩者各打一局单人对 AI，收集三个固定问题的反馈。
- [ ] 无剪辑 Demo、`v1.0.0` tag、release notes。
- [ ] 2 分钟中英文项目介绍 + 5 个深挖问题答案。

**验收：** 公开仓库、release、Demo、试玩反馈、指标来源表。

## 5. 暂缓项

| 暂缓项 | 涉及原 Task | 具体内容 |
| --- | --- | --- |
| 联机 | Task 6；Task 4 / 5 / 11 中的多真人部分 | `POST /rooms/{code}/join`、多真人同房间、WebSocket 同步、断线重连、五浏览器 E2E、真人 + AI 混合局 |
| 11–12 人扩展规则 | Task 2、Task 12 部分 | `extended_v0`、10,000 局模拟、20 局真人试玩 |
| 多实例与 Redis | M4 | 负载测试、故障测试 |

联机没有排期。为了以后加回来不重写，v0.2–v0.6 遵守这几条约束：

- 所有动作带 `player_id` 和 `expected_version`，bot 和真人走同一条 command path。
- 视图始终按玩家生成，不存在“全局视图”接口。
- 事件带递增 `version`。
- 前端不推断阶段和胜负，只展示服务器状态。

联机完成前，简历和 README 不出现“实时”“多人联机”的表述。

## 6. 时间 target

假设从 2026-11-23 起每周 15 小时，并留出节假日余量：

| 版本 | 完成 target |
| --- | --- |
| v0.1 | 2026-11 月底 |
| v0.2 | 2026-12 月下旬 |
| v0.3 | 2027-01 月下旬 |
| v0.4 | 2027-02 月上旬 |
| v0.5 | 2027-02 月下旬 |
| v0.6 – v1.0 | 2027 S1 学期内，按实际工时再排 |

每个版本先达到验收标准再进入下一个；课程高压周只完成最小可演示切片。
