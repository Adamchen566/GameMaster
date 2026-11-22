# Avalon AI Game Master

一个用于训练完整软件工程链路的阿瓦隆项目：React/TypeScript 前端、FastAPI 后端、PostgreSQL、确定性规则引擎，以及受限工具调用的 AI 主持和 AI 玩家。当前路线先做官方 5–10 人的单人对 AI 闭环；多人联机和 11–12 人扩展规则暂缓。

当前阶段：v0.4 持久化已实现——一名真人加机器人，在浏览器里打完一局官方 5–10 人阿瓦隆；对局以事件日志存进 PostgreSQL，后端重启后刷新页面能回到同一局。v0.5 上线暂时跳过；v0.6 AI 已接进对局：建房时可以把席位交给模型、打开 AI 主持（需要服务器配置模型，见下）；v0.7 评测的用例、运行器和结构化日志已完成；v0.8 把界面改成圆桌，加入了轮流发言，补位的机器人会推理、会说理由。**还没有用真实密钥调用过模型**，所以下面的数字里没有 Claude。

## 从这里开始

1. 阅读 [`docs/roadmap.md`](docs/roadmap.md)，确认当前版本和验收标准。
2. 阅读 [`docs/getting-started.md`](docs/getting-started.md)，了解 AI 五等级和文件职责。
3. 按下面的“本地运行”把环境跑通。

## 本地运行

后端（Python 3.12）。用 `py -3.12` 而不是 `python` 建环境：机器上同时装着别的 Python 版本时，`python` 不一定指向 3.12。

```powershell
cd apps/api
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

前端（Node 22 或 24 均可，CI 和容器用 24；pnpm 由 Node 自带的 corepack 提供，不用单独安装）：

```powershell
cd apps/web
corepack pnpm install
corepack pnpm test
corepack pnpm dev
```

这样启动的后端把对局放在内存里，重启即丢。想在本机不装数据库也能保留对局，启动前设置 `DATABASE_URL` 并建表（PostgreSQL 的写法见 [`docs/database.md`](docs/database.md)）：

```powershell
cd apps/api
$env:DATABASE_URL = "sqlite:///./avalon.db"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000
```

想让 AI 上桌，每个座位可以单独选由谁来打。三种来源，配好哪个，大厅里就能选哪个：

| 来源 | 需要什么 | 花费 |
| --- | --- | --- |
| Claude（API） | `ANTHROPIC_API_KEY` | 每个回合一次付费调用 |
| DeepSeek（API） | `DEEPSEEK_API_KEY` | 每个回合一次付费调用 |
| 本机 Claude Code | 装好 Claude Code 并登录一次（终端运行 `claude`），不要密钥 | 用你自己的订阅额度，每步十几秒到一两分钟 |

密钥写进 `apps/api/.env`（照 [`apps/api/.env.example`](apps/api/.env.example) 复制一份，已被 git 忽略），重启后端生效。每局有 token 上限（默认 30 万，`LLM_MAX_TOKENS_PER_GAME`）；全部配置项见 [`docs/architecture.md`](docs/architecture.md) 第 5.1 节。AI 主持只用 API（Claude 或 DeepSeek），Claude Code 太慢，不用来主持。

也可以只看不打：大厅里选“观战”，所有座位都由 AI 来打，你能看到每个人的身份和“心声”（每个 AI 做决定时的真实想法）；上桌打的对局结束后，也能在复盘里看到所有心声。浏览器支持时可以打开“朗读”，用浏览器自带的声音念出每一句话（每个角色音高、语速不同）。

先按上面启动后端，再打开 <http://localhost:5173>：输入昵称、选人数、创建对局，就可以和机器人打一局。对局是一张圆桌：队长选人后，从队长开始每人发言一次（可以点名你怀疑的人），然后全体投票；机器人会根据任务结果、投票和点名判断谁可疑，并说出理由。页面请求 `/api/...`，由 Vite 代理转发到后端；后端不在 `http://127.0.0.1:8000` 时用环境变量 `API_PROXY_TARGET` 指定。

整套环境（Docker Compose，含 PostgreSQL）：

```powershell
Copy-Item .env.example .env
docker compose up --build --wait
```

同样打开 <http://localhost:5173>，看到“服务在线”即三个容器都正常。API 容器启动时会自动执行数据库迁移，对局存在 `postgres-data` 卷里。

在终端看一局随机对局（同样的参数永远是同一局）：

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m app.game.simulate --players 7 --seed 42
```

## 评测

173 个固定用例（玩家决策 141、主持 32）加整局对比，全部可以不花钱地跑一遍来检查管线：

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m app.evals.run --provider hostile --out eval-out
```

| 实测数字（2026-11-22） | 值 |
| --- | --- |
| 随机 bot 对随机 bot，好人胜率（每种人数 500 局） | 5 人 11.6%，6 人 11.6%，7 人 9.6%，8 人 7.2%，9 人 11.6%，10 人 8.4% |
| 会推理的机器人互打，好人胜率（每种人数 500 局） | 5 人 35.6%，6 人 24.6%，7 人 13.8%，8 人 14.4%，9 人 20.6%，10 人 16.6% |
| 故意捣乱的替身模型，141 个回合里最终动作合法 | 141 / 141（其中 65.2% 靠回退） |
| 同一次运行里发给模型的秘密 | 0 |
| Claude 的合法率、延迟、成本、胜率 | 还没跑，需要密钥 |

怎么读这些数字、用例怎么来的、哪些没覆盖，见 [`docs/evidence/agent-evaluation.md`](docs/evidence/agent-evaluation.md)。

后端日志是每行一个 JSON 对象，带 `request_id`、`game_id`、`event_id`；想在终端里读纯文本就设 `LOG_FORMAT=text`。

## 文档

| 文档 | 用途 |
| --- | --- |
| [`docs/roadmap.md`](docs/roadmap.md) | 版本顺序、范围、验收标准；顺序和范围以它为准 |
| [`docs/architecture.md`](docs/architecture.md) | 规则引擎、单人对局后端和前端的模块、状态图、接口、可见性规则 |
| [`docs/database.md`](docs/database.md) | 表结构、ER 图、事件追加的事务与乐观并发、五条查询 |
| [`docs/threat-model.md`](docs/threat-model.md) | AI 玩家和 AI 主持的信任边界、威胁、对策和对应测试 |
| [`docs/evidence/agent-evaluation.md`](docs/evidence/agent-evaluation.md) | 评测用例、指标定义、基线数字、失败样例、人工标注方法 |
| [`docs/superpowers/plans/2026-09-15-avalon-ai-game-master.md`](docs/superpowers/plans/2026-09-15-avalon-ai-game-master.md) | 每个 Task 的详细步骤、接口和 AI 等级 |
| [`docs/getting-started.md`](docs/getting-started.md) | AI 五等级规则、目录结构、文件职责 |
| [`docs/learning-log.md`](docs/learning-log.md) | 每个切片的本人复盘 |

