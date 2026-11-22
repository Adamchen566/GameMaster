# 运行手册

线上地址：<https://avalon.jiashao.tech>。服务器是腾讯云香港那台（和眠屿 API、AI 中转站、知集官网同一台），Ubuntu 26.04，2 核 2 GB。

## 1. 组成

| 部分 | 位置 | 说明 |
| --- | --- | --- |
| 后端 | systemd `avalon-api`，`127.0.0.1:4177` | uvicorn，Python 3.14 venv `/opt/avalon/venv`，用户 `avalon`，内存上限 400 MB |
| 代码 | `/opt/avalon/app` → `/opt/avalon/releases/<时间>-<提交>` | 每次部署一个新目录，保留最近 5 个 |
| 前端 | `/opt/avalon/web` → 当前版本的 `apps/web/dist` | Caddy 直接发静态文件 |
| 数据 | `/opt/avalon/data/avalon.db` | SQLite，只有 `avalon` 用户能读写 |
| 配置 | `/opt/avalon/api.env` | root 所有、`avalon` 组可读；密钥只在这里 |
| 入口 | `/etc/caddy/Caddyfile` 里的 `avalon.jiashao.tech` 块（副本 [`deploy/Caddyfile.avalon`](../deploy/Caddyfile.avalon)） | `/api/*` 去掉前缀转给后端，其余是前端；HTTPS 证书 Caddy 自动申请 |

模型：线上只开 DeepSeek（`LLM_DRIVERS=deepseek`），本机 Claude Code / Codex 不在服务器上。任何人都能开局，所以有两道上限：每局 20 万 token，整台服务器每天（UTC）200 万 token。到了上限，模型座位由机器人代打，界面上会标出来。每日计数在内存里，**重启后端会清零**。

## 2. 部署

在本机仓库根目录，Git Bash：

```bash
bash deploy/deploy.sh
```

它会：检查工作区干净 → 构建前端 → 打包后端代码、迁移、前端产物 → 上传 → 在服务器上解压成新版本、装依赖、切换软链接、重启 → 等 `/health` 答复。20 秒内没答复就自动切回上一个版本并打印日志。数据库迁移在后端启动时自动执行（`AUTO_MIGRATE=true`）。

## 3. 回滚

```bash
bash deploy/deploy.sh rollback
```

切回上一个版本目录并重启。**数据库不回滚**：迁移只加表加列，旧代码能读新库；如果哪天有删列的迁移，回滚前要先恢复备份。

## 4. 日常

| 要做的事 | 命令（在服务器上） |
| --- | --- |
| 看状态 | `systemctl status avalon-api` |
| 看日志 | `journalctl -u avalon-api -f`（每行一个 JSON） |
| 健康检查 | `curl -s 127.0.0.1:4177/health`，外面 `curl -s https://avalon.jiashao.tech/api/health` |
| 改配置 / 换密钥 | `sudo nano /opt/avalon/api.env`，然后 `sudo systemctl restart avalon-api` |
| 备份数据库 | `sudo -u avalon /opt/avalon/venv/bin/python -c "import sqlite3; sqlite3.connect('/opt/avalon/data/avalon.db').backup(sqlite3.connect('/opt/avalon/data/backup.db'))"` |
| 导出一局 | `sudo -u avalon bash -c 'set -a; . /opt/avalon/api.env; cd /opt/avalon/app/apps/api; /opt/avalon/venv/bin/python -m app.records <game_id> --out /tmp/<game_id>.json'` |

## 5. 改 Caddy

同一个 Caddy 还在服务 `api.jiashao.tech`、`ai.jiashao.tech`、`jiashao.tech`。改之前：

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.bak-$(date +%F-%H%M)
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
```

`validate` 不过就不要 `reload`。

## 6. 出问题时

| 现象 | 先看 |
| --- | --- |
| 网页打不开 | `systemctl status caddy`；DNS 是否指向 119.28.31.238（用 `https://dns.google/resolve?name=avalon.jiashao.tech` 查，墨尔本本地的 nslookup 会误报） |
| 页面在但显示“无法连接服务” | `systemctl status avalon-api`，`journalctl -u avalon-api -n 50` |
| AI 座位全变成“机器人代打：预算用完” | 到了每日上限；等 UTC 零点，或调高 `LLM_MAX_TOKENS_PER_DAY` 后重启 |
| AI 座位“服务不可用” | DeepSeek 密钥错或余额不足；看日志里的 `fallback_reason` |
| 内存不够 | `free -h`；后端被 systemd 限制在 400 MB，超了会被重启 |

## 7. 演练记录

| 日期（UTC） | 做了什么 | 结果 |
| --- | --- | --- |
| 2026-11-22 09:55 | 首次部署 `4059ca2`；服务器上开一局 12 人观战局并取回放 | 健康检查通过；对局打完，扩展规则，139 条公开记录 |
| 2026-11-22 09:56 | 同一提交再部署一次（新版本目录 `20261122095656`），然后 `deploy.sh rollback` | 2.9 秒切回 `20261122095524`，`/health` 正常，库里的对局还在 |
| 2026-11-22 09:55 | 加 Caddy 块：备份 → `caddy validate` → `reload` | 只增加行；`jiashao.tech` 200、`ai.jiashao.tech` 302、`api.jiashao.tech/privacy` 200，和改之前一样 |

## 8. 还没做

- 没有自动备份；没有监控和告警。
- 没有按 IP 限制开局频率，费用只靠 token 上限兜底。
- 回放用的令牌存在浏览器 `localStorage`，见 [`threat-model.md`](threat-model.md)。
