# 指标来源表

简历和 README 里出现的每一个数字都在这里，写明怎么来的、怎么复现。测量日期都是 2026-11-22，提交 `2cf8bc6`（PR 14 合并后）。没有测过的写“没有”，不估算。

## 工程

| 指标 | 数值 | 来源 / 复现 |
| --- | --- | --- |
| 后端测试 | 850 个通过，48 个跳过 | `cd apps/api && pytest`。跳过的 48 个只在设置 `TEST_DATABASE_URL`（PostgreSQL）时运行，CI 里设置了 |
| 后端行覆盖率 | 98%（4,178 条语句里 82 条未覆盖，含分支） | `pytest --cov=app` |
| 前端测试 | 125 个通过 | `cd apps/web && corepack pnpm test` |
| 前端覆盖率 | 没有测 | — |
| 类型检查 | 后端 `mypy --strict` 0 错误（本地跑，CI 里没有）；前端 `tsc -b` 0 错误（CI 里跑） | `uvx mypy --strict app`；`corepack pnpm typecheck` |
| CI 时长 | 约 2.5–3 分钟（三个任务并行：后端、前端、Compose 冒烟） | GitHub Actions `ci.yml` 最近 6 次成功运行 |
| 代码量 | 后端 9,000 行、测试 8,136 行；前端 3,156 行、测试 2,260 行 | `wc -l`，含空行和注释 |
| 合并的 PR | 13 个（PR 1–14，PR 5 关闭未合并） | GitHub |

## 规则引擎

| 指标 | 数值 | 来源 / 复现 |
| --- | --- | --- |
| 支持人数 | 官方 5–10 人，自定扩展 11–12 人 | `app/game/rulesets.py`，测试 `tests/game/test_rulesets.py` |
| 属性测试 | 5–12 人随机合法动作打完整局，按事件重放得到同一终局 | `tests/game/test_properties.py`（Hypothesis） |

## AI 玩家和主持

| 指标 | 数值 | 来源 / 复现 |
| --- | --- | --- |
| 评测用例 | 玩家 149 例（含 40 个注入/越权攻击），主持 32 例 | `apps/api/evals/cases/` |
| 防线自检（故意捣乱的替身，141 例） | 最终动作 100% 合法；65.2% 的回合被回退；发给模型的秘密 0 | [`agent-evaluation.md`](agent-evaluation.md) 4.2 |
| Codex：最终动作合法率 | 100%（149/149） | [`eval-codex/report.md`](eval-codex/report.md)，`python -m app.evals.run --provider codex --suites players,gm` |
| Codex：首答合法率 | 98.7% | 同上 |
| Codex：越权率 | 0%（攻击用例中也是 0%） | 同上 |
| Codex：发言注入 | 8/8 没照做 | 同上，用例 `player-142` 到 `player-149` |
| Codex：金标命中 | 31/31 | 同上 |
| Codex：回退率 | 1.3%（2 例超时） | 同上 |
| Codex：延迟 | P50 6.6 秒，P95 48.1 秒 | 同上 |
| Codex：主持文字被采用 | 96.9%（1 例超时用模板） | 同上 |
| 真实整局 | 5 人观战局，Codex 打 22 个回合全部由模型完成，144 秒 | [`games/codex-spectated-5p.json`](games/codex-spectated-5p.json) |
| Claude / DeepSeek 的数字 | 没有（需要付费密钥） | — |
| 主持文字的人工标注 | 没有（31 条待标） | `eval-codex/gm_labels.csv` |

## 基线

| 指标 | 数值 | 来源 / 复现 |
| --- | --- | --- |
| 随机 bot 对随机 bot，好人胜率 | 7.2%–11.6%（5–10 人，各 500 局） | [`agent-evaluation.md`](agent-evaluation.md) 4.1 |
| 会推理的机器人互打，好人胜率 | 5–10 人 13.8%–35.6%（各 500 局）；5–12 人 10%–41%（各 200 局） | 同上 4.1、4.4 |
| 机器人当好人对随机邪恶 | 62.2%–67.8% | 同上 4.1 |

## 产品

| 指标 | 数值 | 来源 |
| --- | --- | --- |
| 真人试玩者 | 0 | 还没有组织试玩 |
| 在线 Demo | 没有 | v0.5 部署暂缓 |
| 线上延迟 / 可用性 | 没有 | 没有部署 |

## 写简历时的边界

- 可以说：确定性规则引擎、事件溯源、按座位脱敏、多模型驱动、评测框架、98% 后端覆盖率、Codex 实测数字。
- 不能说：“实时多人联机”（没做）、“已上线”（没部署）、“用户反馈”（没试玩）、Claude / DeepSeek 的效果（没跑）。
