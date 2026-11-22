# Avalon AI Game Master

一个用于训练完整软件工程链路的阿瓦隆项目：React/TypeScript 前端、FastAPI 后端、PostgreSQL、确定性规则引擎，以及受限工具调用的 AI 主持和 AI 玩家。当前路线先做官方 5–10 人的单人对 AI 闭环；多人联机和 11–12 人扩展规则暂缓。

当前阶段：v0.2 规则引擎已实现（官方 5–10 人，纯 Python，事件驱动），等待本人逐文件 review。下一步是 v0.3 单人可玩。

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

打开 <http://localhost:5173>。页面请求 `/api/health`，由 Vite 代理转发到后端；后端不在 `http://127.0.0.1:8000` 时用环境变量 `API_PROXY_TARGET` 指定。

整套环境（Docker Compose，含 PostgreSQL）：

```powershell
Copy-Item .env.example .env
docker compose up --build --wait
```

同样打开 <http://localhost:5173>，看到“服务在线”即三个容器都正常。

在终端看一局随机对局（同样的参数永远是同一局）：

```powershell
cd apps/api
.\.venv\Scripts\python.exe -m app.game.simulate --players 7 --seed 42
```

## 文档

| 文档 | 用途 |
| --- | --- |
| [`docs/roadmap.md`](docs/roadmap.md) | 版本顺序、范围、验收标准；顺序和范围以它为准 |
| [`docs/architecture.md`](docs/architecture.md) | 规则引擎的模块、状态图、动作与事件、规则表 |
| [`docs/superpowers/plans/2026-09-15-avalon-ai-game-master.md`](docs/superpowers/plans/2026-09-15-avalon-ai-game-master.md) | 每个 Task 的详细步骤、接口和 AI 等级 |
| [`docs/getting-started.md`](docs/getting-started.md) | AI 五等级规则、目录结构、文件职责 |
| [`docs/learning-log.md`](docs/learning-log.md) | 每个切片的本人复盘 |

