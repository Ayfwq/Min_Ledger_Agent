# Mini Ledger Agent

[![CI](https://github.com/Ayfwq/Min_Ledger_Agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Ayfwq/Min_Ledger_Agent/actions/workflows/ci.yml)
[![Deploy](https://github.com/Ayfwq/Min_Ledger_Agent/actions/workflows/deploy.yml/badge.svg)](https://github.com/Ayfwq/Min_Ledger_Agent/actions/workflows/deploy.yml)

> 可澄清、可追溯的智能记账助手 —— 文本 / 截图输入，自动抽取多笔账单，主动澄清缺失与冲突，人工审核后入账。

一个完整的全栈作业项目：**FastAPI + PostgreSQL + 硅基流动 LLM + Vue 3**，支持 Docker Compose 部署与 GitHub Actions CI/CD。

## 界面预览

| 工作台 | 审核台 |
|---|---|
| ![工作台](docs/screenshots/workbench.png) | ![审核台](docs/screenshots/review.png) |

| 处理详情（澄清 / 数据源 / 轨迹） | 正式账单 |
|---|---|
| ![处理详情](docs/screenshots/input-detail.png) | ![正式账单](docs/screenshots/bills.png) |

移动端适配：

<p>
  <img src="docs/screenshots/mobile-workbench.png" width="260" alt="移动端工作台" />
  <img src="docs/screenshots/mobile-detail.png" width="260" alt="移动端详情" />
</p>

---

## 功能一览

| 能力 | 说明 |
|------|------|
| 文本输入 | 一段自然语言可包含多笔消费，自动拆分 |
| 截图输入 | 上传订单/交易截图，视觉模型识别，图片持久化保存 |
| 结构化字段 | 金额、日期、商户、类别、说明，逐字段记录来源（文本/截图/用户补充） |
| 主动澄清 | 关键字段缺失、字段冲突时逐条提问，支持多轮补充、暂不提供、取消 |
| 冲突保护 | 用户补充与识别结果不一致时必须二选一，绝不静默覆盖 |
| 业务数据源 | ① 历史账单/草稿查重 ② 商户目录标准化，独立调用、独立失败、独立重试 |
| 人工审核 | 编辑、确认入账、拒绝；关键字段缺失或冲突未解决时禁止确认 |
| 幂等入账 | 同一草稿并发/重复确认只生成一条账单（数据库唯一约束 + 行锁） |
| 全链路追溯 | 每一步的状态、耗时、数据源结果、失败原因、重试记录 |
| 异常恢复 | LLM 超时/格式错误、数据源失败、服务重启后可继续处理 |
| 访问保护 | 可选共享密码（`APP_PASSWORD`） |

---

## 架构

```
Vue 3 + Element Plus (SPA)
        │  /api/v1  /uploads
   Nginx (web 容器)
        │
   FastAPI (backend 容器)
   ├── API 层        inputs / drafts / bills / clarifications / merchants
   ├── Pipeline      extract → validate → clarify → datasource → draft
   ├── Job Worker    PostgreSQL 任务队列，FOR UPDATE SKIP LOCKED
   └── LLM Client    硅基流动（文本 + 视觉），重试 + JSON 校验
        │
   PostgreSQL 16  +  data/uploads (volume)
```

---

## 技术栈

- **后端**：Python 3.12、FastAPI、SQLAlchemy 2 (async)、asyncpg、Alembic、Pydantic v2、uv
- **数据库**：PostgreSQL 16
- **模型**：硅基流动 OpenAI 兼容接口
  - 文本抽取：`deepseek-ai/DeepSeek-V3.2`
  - 截图识别：`Qwen/Qwen3-VL-32B-Instruct`
- **前端**：Vue 3 + TypeScript + Vite + Pinia + Vue Router + Element Plus
- **部署**：Docker Compose、Nginx、GitHub Actions、GHCR

---

## 目录结构

```
.
├── backend/
│   ├── app/
│   │   ├── api/routes.py          # REST API
│   │   ├── services/
│   │   │   ├── llm.py             # 硅基流动客户端 + 抽取提示词
│   │   │   ├── pipeline.py        # 抽取/校验/澄清状态机
│   │   │   ├── datasources.py     # 查重 + 商户目录
│   │   │   ├── ledger.py          # 编辑/确认/拒绝/重试
│   │   │   └── worker.py          # DB 任务队列
│   │   ├── models.py              # 数据模型
│   │   ├── schemas.py             # 请求/响应模型
│   │   └── main.py
│   ├── migrations/                # Alembic（含商户目录种子数据）
│   ├── tests/                     # pytest（11 个用例）
│   ├── Dockerfile
│   └── pyproject.toml / uv.lock
├── frontend/
│   ├── src/{views,components,api}
│   ├── Dockerfile / nginx.conf
│   └── package.json / package-lock.json
├── deploy/
│   ├── docker-compose.prod.yml
│   ├── deploy.sh                  # 服务器端发布 + 健康检查 + 回滚
│   ├── server-bootstrap.sh
│   └── .env.example
├── .github/workflows/{ci.yml,deploy.yml}
├── docker-compose.dev.yml
└── docs/{PLAN.md,DEPLOY.md}
```

---

## 本地开发

### 1. 启动 PostgreSQL

```bash
docker compose -f docker-compose.dev.yml up -d
```

（端口 `5433`，用户/密码/库名均为 `ledger`）

### 2. 后端

```bash
cd backend
cp .env.example .env          # 填入 SILICONFLOW_API_KEY
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000
```

- API 文档：<http://127.0.0.1:8000/docs>
- 健康检查：<http://127.0.0.1:8000/api/v1/health>

### 3. 前端

```bash
cd frontend
npm install
npm run dev                   # http://127.0.0.1:5173
```

Vite 已配置 `/api` 与 `/uploads` 代理到 `127.0.0.1:8000`。

### 4. 测试

```bash
cd backend
uv run ruff check app tests
uv run pytest -q
```

测试使用 SQLite + 模拟 LLM，不需要数据库与 API Key，可在 CI 中直接运行。

---

## 环境变量（`backend/.env`）

| 变量 | 说明 | 默认 |
|------|------|------|
| `DATABASE_URL` | asyncpg 连接串 | `postgresql+asyncpg://ledger:ledger@127.0.0.1:5433/ledger` |
| `SILICONFLOW_API_KEY` | 硅基流动 API Key | 空（必填） |
| `SILICONFLOW_BASE_URL` | API 地址 | `https://api.siliconflow.cn/v1` |
| `LLM_TEXT_MODEL` | 文本模型 | `deepseek-ai/DeepSeek-V3.2` |
| `LLM_VISION_MODEL` | 视觉模型 | `Qwen/Qwen3-VL-32B-Instruct` |
| `LLM_PROXY` | 可选代理；留空直连（会忽略系统 `HTTP_PROXY`） | 空 |
| `UPLOAD_DIR` | 图片存储目录 | `data/uploads` |
| `APP_PASSWORD` | 访问密码，空表示不启用 | 空 |
| `ALLOWED_ORIGINS` | CORS 白名单，逗号分隔 | `http://localhost:5173` |

---

## API 概览（`/api/v1`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/inputs` | 文本输入 `{text}` |
| POST | `/inputs/upload` | 截图上传（multipart `file`） |
| GET | `/inputs` | 输入列表（`status` 过滤） |
| GET | `/inputs/{id}` | 详情：草稿 / 澄清 / 轨迹 / 数据源 |
| POST | `/inputs/{id}/retry` | 失败后从断点重试 |
| POST | `/clarifications/{id}/answer` | `{action: answer\|unknown\|choose, value?, choice?}` |
| POST | `/clarifications/{id}/cancel` | 取消澄清 |
| GET | `/drafts` | 草稿列表（`status` 过滤） |
| PATCH | `/drafts/{id}` | 编辑；覆盖识别值需 `force: true`（否则 409） |
| POST | `/drafts/{id}/confirm` | 确认入账；支持 `Idempotency-Key` |
| POST | `/drafts/{id}/reject` | 拒绝 |
| POST | `/drafts/{id}/datasources/{source}/retry` | 单数据源重试 |
| GET | `/bills` | 正式账单 |
| GET | `/merchants?q=` | 商户目录查询 |
| GET | `/stats` / `/health` | 统计 / 健康检查 |

---

## 关键设计

### 澄清状态机

- 关键字段（金额、日期）缺失 → **阻塞式**澄清，禁止确认入账；
- 商户/类别缺失 → 非阻塞问题 + 警告，不编造默认值；
- 已回答字段不会重复提问；`不知道` 会记录并保持阻塞；
- 冲突问题需要明确选择「识别值 / 用户补充值」。

### 幂等与并发

- 草稿按 `(input_id, seq)` 唯一，重试只更新不新增；
- 确认时 `SELECT ... FOR UPDATE` + `bills.draft_id UNIQUE`；
- 重复确认返回同一账单（`idempotent: true`）。

### 可追溯

`trace_events` 记录：创建、抽取（模型/耗时/条数）、生成草稿、数据源调用、澄清问答、冲突处理、人工编辑、确认/拒绝、任务重试与失败原因。

---

## 部署

见 [docs/DEPLOY.md](docs/DEPLOY.md)。简要流程：

1. 服务器执行 `deploy/server-bootstrap.sh` 安装 Docker；
2. 在 `/opt/min-ledger/.env` 填写生产配置；
3. 配置 GitHub Secrets：`SSH_HOST`、`SSH_USER`、`SSH_KEY` 或 `SSH_PASSWORD`、`SSH_PORT`（可选）、`GHCR_PAT`（可选）；
4. push 到 `main` → Actions 构建镜像 → SSH 部署 → 健康检查失败自动回滚。

---

## 安全提示

- `.env` 已被 `.gitignore` 排除，**不要提交任何 API Key**；
- 生产环境请设置 `APP_PASSWORD`，并通过 HTTPS（Caddy / Nginx + certbot）暴露服务；
- 如果 Key 曾出现在聊天记录、日志或截图中，建议到硅基流动控制台**重置**。

---

## 实现进度

| 模块 | 状态 |
|------|------|
| 数据模型 + Alembic 迁移（含 30 条商户种子） | ✅ |
| 文本 / 截图抽取（硅基流动 DeepSeek + Qwen3-VL） | ✅ |
| 澄清状态机、冲突确认、暂不提供、取消 | ✅ |
| 查重 + 商户目录（独立失败/重试/轨迹） | ✅ |
| 审核编辑、幂等确认、拒绝、并发保护 | ✅ |
| Vue 3 工作台 / 详情 / 审核台 / 账单 | ✅ |
| Docker Compose + Nginx 本地整栈验证 | ✅ |
| GitHub Actions CI（lint / test / build） | ✅ |
| GHCR 构建推送 + SSH 部署脚本（含回滚） | ✅ |
| 服务器上线（Docker Compose + 宿主机 Nginx 反代） | ✅ |
| GitHub Actions 自动部署到服务器 | ✅ |

