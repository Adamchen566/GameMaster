# 开工指南：严格执行 AI 五等级

## 1. 本项目如何使用 AI

AI 等级描述的是**单个任务**，不是整个项目永久处于同一级。每次工作前必须先写 `AI level`，执行中不得临时升级；需要升级时，先停止、记录原因，再重新定义任务。

| 等级 | AI 权限 | 你的责任 | 当前例子 |
| --- | --- | --- | --- |
| L0 无 AI | AI 不给实现、补全或排错答案 | 从空文件写、运行、阅读错误、自己修改 | `app/main.py`、基础 Python/TS/SQL/Git |
| L1 教练 | 只解释概念、追问思路、给文档关键词 | 先给自己的解释，再根据概念独立实现 | HTTP、状态机、事务、async |
| L2 审阅/排障 | 只看你已写的代码和证据，指出风险或给逐级提示 | 先独立排查至少 25 分钟 | 测试失败、重构、竞态 |
| L3 结对生产 | 可生成样板、配置、CSS、测试数据、文档初稿 | 逐行 review，运行全部验证 | `.gitignore`、CI、Docker、页面样式 |
| L4 受控 Agent | 可在隔离分支完成验收明确的低风险任务 | 先写规格/测试边界，审查每个 diff | 项目后期重复 CRUD 或文档更新 |

### 不可违反的规则

1. 规则引擎关键状态转换、第一次 React reducer、第一次 SQL JOIN、第一次 WebSocket 重连状态机必须由本人以 L0/L1 完成。
2. 只有已经存在“你的尝试 + 失败证据”时，才能进入 L2。
3. L3/L4 代码如果无法在不看 AI 对话的情况下解释，就不能合并。
4. 每个工作日先完成 30 分钟 L0，再使用更高等级。
5. 每周选择一个 AI 帮过的知识点，隔几天从空文件无 AI 重做。

## 2. 已准备好的本地环境

| 项目 | 当前状态 | 用途 |
| --- | --- | --- |
| Node.js 24 / npm 11 | 已安装 | React/TypeScript 工具链 |
| Python 3.12 | 使用项目 `.venv` | FastAPI 和测试 |
| Docker 29 / Compose 5 | 已安装 | 后续 PostgreSQL 和完整本地环境 |
| Python 依赖 | 已安装到 `.venv` | FastAPI、pytest、httpx、ruff、uvicorn |
| 后端失败测试 | 已创建 | 驱动第一个 L0 实现 |

PowerShell 进入项目：

```powershell
Set-Location 'D:\BackUp\self-work\GameMaster'
```

激活 Python 环境：

```powershell
.\.venv\Scripts\Activate.ps1
```

如果 PowerShell 阻止激活，不需要修改系统策略，直接使用：

```powershell
.\.venv\Scripts\python.exe -m pytest .\apps\api\tests\test_health.py -q
```

当前预期结果：测试收集失败，并显示 `ModuleNotFoundError: No module named 'app'`。这是因为业务应用还没有创建，不是环境损坏。

## 3. 项目最终结构与每个文件的职责

```text
GameMaster/
├─ apps/
│  ├─ api/
│  │  ├─ app/
│  │  │  ├─ main.py                 # FastAPI 组装入口，只负责注册路由/生命周期
│  │  │  ├─ api/rooms.py            # 创建、加入、离开房间的 HTTP 边界
│  │  │  ├─ api/games.py            # 将玩家请求转换成游戏 Action
│  │  │  ├─ api/ws.py               # WebSocket 鉴权、连接与消息协议
│  │  │  ├─ core/config.py          # 环境变量与强类型配置
│  │  │  ├─ core/logging.py         # JSON 日志和 correlation id
│  │  │  ├─ db/models.py            # SQLAlchemy 持久化模型
│  │  │  ├─ db/session.py           # 数据库连接和事务生命周期
│  │  │  ├─ game/state.py           # 不可变 GameState/PlayerState
│  │  │  ├─ game/actions.py         # 玩家可请求的命令类型
│  │  │  ├─ game/events.py          # 已确认发生的领域事件
│  │  │  ├─ game/rulesets.py        # 5–10 官方、11–12 实验规则配置
│  │  │  ├─ game/engine.py          # 纯函数状态转换和规则校验
│  │  │  ├─ game/views.py           # 为不同身份生成最小可见视图
│  │  │  ├─ game/repository.py      # 事件追加、版本检查和状态回放
│  │  │  ├─ realtime/hub.py         # 在线连接登记和个性化广播
│  │  │  ├─ gm/service.py           # AI GM：只读公开状态并生成旁白
│  │  │  ├─ agents/contracts.py     # AI 玩家 observation/action 契约
│  │  │  ├─ agents/player_agent.py  # 模型工具调用与回合决策
│  │  │  └─ agents/policy_fallback.py # 模型失败时的合法动作策略
│  │  ├─ tests/                      # 与 app 结构对应的单元/集成测试
│  │  ├─ alembic/                    # PostgreSQL schema 迁移
│  │  └─ pyproject.toml              # Python 依赖与工具配置
│  └─ web/
│     ├─ src/api/client.ts           # HTTP client 与错误类型
│     ├─ src/features/lobby/         # 创建/加入房间 UI
│     ├─ src/features/game/          # 阶段界面和客户端状态
│     ├─ src/features/gm/            # AI 主持旁白面板
│     ├─ src/lib/socket.ts           # 连接、重连、消息版本控制
│     ├─ src/routes/                 # 页面入口
│     └─ package.json                # 前端依赖与命令
├─ evals/                             # AI GM/玩家离线评测与模拟
├─ docs/                              # 架构、ADR、学习与简历证据
├─ .github/workflows/ci.yml           # 自动检查、测试和构建
├─ compose.yaml                       # web/api/postgres 本地组合
├─ .env.example                       # 可公开变量名和安全示例
└─ README.md                          # 招聘者三分钟项目入口
```

### 文件编写原则

- `api/` 文件只处理协议：读取请求、鉴权、调用应用逻辑、映射响应；不写游戏规则。
- `game/` 文件不得导入 FastAPI、SQLAlchemy、WebSocket 或 LLM SDK，因此可以快速、确定性测试。
- `db/` 只处理持久化，不判断谁能投票或任务是否成功。
- `views.py` 是秘密信息的唯一出口；不得把数据库对象直接序列化给客户端或 AI。
- `gm/` 没有状态写权限；`agents/` 只能提交与真人相同的动作。
- 前端不推断胜负或阶段，只展示服务器提供的状态和 `legalActions`。
- 每个实现文件必须有对应测试；测试描述用户可观察行为，不绑定内部写法。

## 4. 现在由你完成的第一个 L0 文件

### 文件

`apps/api/app/main.py`

### 目标

创建一个 FastAPI 应用，使现有测试通过。

### 必须满足的行为

1. 从 `fastapi` 导入创建应用所需对象。
2. 模块顶层暴露名为 `app` 的 FastAPI 实例。
3. 注册 `GET /health`。
4. 正常响应状态码为 200。
5. JSON 必须精确等于 `{"status": "ok"}`，不要添加时间、数据库状态或额外字段。
6. 该文件暂时不连接数据库、不读取环境变量、不写日志中间件。

### 建议思考顺序

1. `TestClient` 为什么要从模块导入 `app`？
2. Python 装饰器如何把函数注册成 GET 路由？
3. Python 字典如何被 FastAPI 转换成 JSON？
4. 为什么健康检查第一版保持最小，而不立刻检查所有依赖？

### 验证命令

```powershell
.\.venv\Scripts\python.exe -m pytest .\apps\api\tests\test_health.py -q
```

成功标准：`1 passed`。之后再运行格式检查：

```powershell
.\.venv\Scripts\python.exe -m ruff check .\apps\api
```

### 完成后你需要告诉 AI 的内容

```text
L0 完成。我创建了 apps/api/app/main.py。
测试结果：……
我认为 TestClient 能找到接口的原因是：……
我最不确定的是：……
请按 L2 审阅，不要直接重写。
```

## 5. 接下来的文件顺序

| 顺序 | 文件/切片 | AI 等级 | 你要掌握的内容 | 完成证据 |
| ---: | --- | --- | --- | --- |
| 1 | `app/main.py` | L0 | FastAPI app、装饰器、JSON 响应 | health test 通过 |
| 2 | `web` 初始化与 API 状态页面 | L1 + L3 CSS | React render、effect/request、三种状态 | 前端测试和截图 |
| 3 | `compose.yaml` | L1 + L3 | 容器、端口、环境变量、服务依赖 | 三服务启动 |
| 4 | `game/state.py` | L0 | dataclass/type、不可变状态 | 状态模型测试 |
| 5 | `game/rulesets.py` | L0/L1 | 配置驱动、5–12 人参数化 | 全人数测试 |
| 6 | `game/actions.py` | L0 | discriminated union、输入边界 | 类型/构造测试 |
| 7 | `game/engine.py` | L0/L2 | 纯函数、状态机、异常 | 90% 分支覆盖率 |
| 8 | PostgreSQL repository | L0 SQL + L2 | schema、事务、索引、乐观锁 | 容器集成测试 |
| 9 | React lobby/game | L0 reducer + L3 UI | 表单、状态、错误、可访问性 | 组件/E2E 测试 |
| 10 | WebSocket | L0/L1/L2 | async、版本、重连、竞态 | 掉线恢复 E2E |
| 11 | AI GM | L1 + L3 SDK | structured output、回退、成本 | GM eval |
| 12 | AI 玩家 | L1/L2/L3 | tool calling、权限、记忆、评测 | 混合对局与基线 |
| 13 | 部署/CI | L1 + L3 | Docker、Linux、流水线、回滚 | 公开 URL/CI |

不要现在一次性创建所有空文件。每个文件在它的失败测试或明确消费者出现时创建，这样每一步都有原因和可验证结果。

