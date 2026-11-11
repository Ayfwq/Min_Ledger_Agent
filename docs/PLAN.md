# Mini Ledger Agent 项目规划

> 目标：实现一个"可澄清、可追溯"的智能记账助手，支持文本/截图输入、多笔抽取、主动澄清、业务数据源、人工审核入账、全链路追溯，并部署到自有服务器，通过 GitHub Actions 完成 CI/CD。

---

## 1. 需求拆解（对照作业 PDF）

| # | 作业要求 | 实现方案 |
|---|---------|---------|
| 1.1 | 手动输入多笔自然语言消费描述 | `POST /api/v1/inputs`，LLM 结构化抽取 `transactions[]` |
| 1.2 | 上传截图、前端预览、后端真实保存、重启可访问 | 图片落盘 `data/uploads/`（Docker volume），DB 记录元数据，静态路由 `/uploads/*` 返回 |
| 1.3 | 原始输入列表，区分文本/截图，展示状态、澄清记录、草稿 | 输入列表 + 详情抽屉，状态机 + 时间轴 |
| 2.1 | 每笔账单字段：金额、日期、商户/说明、类别、信息来源 | `drafts` 表 + `field_sources` JSONB（text / image / user / datasource） |
| 2.2 | 一条输入可提取多笔 | `transactions[]`，`drafts(input_id, seq)` 唯一 |
| 2.3 | 截图模糊/遮挡/字段缺失 | 视觉模型 + 置信度 + 缺失字段检测；低置信标记 warning |
| 2.4 | 金额/日期为关键字段，缺失不能生成可确认草稿 | 校验器：critical 缺失 → `needs_clarification`，禁止 confirm |
| 2.5 | 商户/类别缺失给警告，不静默编造 | 非关键字段缺失 → warning + 可选澄清；绝不填充默认值 |
| 2.6 | 多笔中仅阻塞不完整的那一笔 | 草稿级独立状态机，互不影响 |
| 3.1 | 主动提问、多轮补充、聚焦最小必要信息 | 澄清规划器：按关键→非关键、每轮只问一个字段 |
| 3.2 | 补充后合并、不重复询问已提供/已确认 | 已回答字段写入 `clarifications`，规划器跳过 |
| 3.3 | "不知道/暂不提供"记录状态并区分关键/非关键处理 | `clarifications.status=unknown`，关键字段保持阻塞 |
| 3.4 | 用户补充与识别结果冲突须提示确认，不得静默覆盖 | 字段级冲突检测，生成 `conflict` 澄清，确认后才替换 |
| 3.5 | 澄清可取消、可暂存、完整问答记录 | `POST .../cancel`，`status=cancelled`，全程留痕 |
| 4.1 | 数据源①：历史账单/草稿查重 | `duplicate_check`：金额容差 + 日期窗口 + 商户相似度，返回疑似重复 |
| 4.2 | 数据源②：商户目录/标准化 | `merchant_catalog`：别名/模糊匹配，返回标准名、建议类别、置信度 |
| 4.3 | 真实查询逻辑、不能万能接口 | 两个独立 service + 独立表 + 独立调用记录 |
| 4.4 | 独立成功/失败/重试，失败展示、重试不丢信息、不重复生成 | `datasource_calls` 独立记录，单源重试，幂等 upsert 草稿 |
| 5.1 | 审核台展示字段、来源、警告、建议；可编辑；确认/拒绝 | `Review` 页面，字段级 source badge |
| 5.2 | 关键字段缺失/冲突未解决不能确认 | 后端强校验 + 前端置灰 |
| 5.3 | 疑似重复提示但人工决定 | 仅提示，不阻断 |
| 5.4 | 重复确认只生成一条账单，并发安全 | `bills.draft_id UNIQUE` + 事务行锁 + Idempotency-Key |
| 6.1 | 全链路追溯 | `trace_events`：步骤、状态、耗时、数据源、失败原因、重试入口 |
| 7.1 | 异常处理：模型失败/超时、格式异常、数据源失败、确认失败、并发 | 统一 `Job` 重试机制 + 失败落库 + 前端重试按钮 |
| 7.2 | 失败不静默，可重试，从失败步骤继续 | 步骤级 checkpoint（`inputs.failure_step`），重试只重跑该步 |
| 7.3 | 重试不重复生成草稿/账单 | 草稿按 `(input_id, seq)` upsert；账单 `draft_id` 唯一 |
| 7.4 | 不能只用内存数组 | PostgreSQL 持久化，Docker volume |
| 7.5 | 重启后全部可查 | 无状态服务 + DB/磁盘持久化 |

---

## 2. 技术选型

| 层 | 选型 | 理由 |
|----|------|------|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2.0 (async) + asyncpg | 异步 IO、OpenAPI 自动文档、类型安全 |
| 依赖管理 | **uv**（`pyproject.toml` + `uv.lock`） | 快、可复现、CI 友好 |
| 数据库 | PostgreSQL 16 | JSONB、数组、行锁、`FOR UPDATE SKIP LOCKED` |
| 迁移 | Alembic | 版本化 schema |
| LLM | 硅基流动 OpenAI 兼容 API | 文本 `deepseek-ai/DeepSeek-V3.2`，视觉 `Qwen/Qwen3-VL-32B-Instruct` |
| 校验 | Pydantic v2 | LLM 输出结构校验 |
| 前端 | Vue 3 + TypeScript + Vite + Pinia + Vue Router + Element Plus + axios | 开发效率高、组件齐全 |
| 部署 | Docker Compose（postgres + backend + web/nginx） | 单机可运维、易回滚 |
| CI/CD | GitHub Actions → GHCR 镜像 → SSH 部署 | 构建一次、多环境可复用 |
| 测试 | pytest + pytest-asyncio + httpx | 覆盖流水线、幂等、并发 |

---

## 3. 系统架构

```
┌──────────────────────────── Browser ────────────────────────────┐
│  Vue3 SPA (Element Plus)                                        │
│  工作台 / 输入详情 / 审核台 / 账单 / 追溯                        │
└───────────────┬─────────────────────────────────────────────────┘
                │ HTTP /api/v1, /uploads
┌───────────────▼─────────────────────────────────────────────────┐
│  Nginx (web 容器) 静态资源 + 反向代理                            │
└───────────────┬─────────────────────────────────────────────────┘
┌───────────────▼─────────────────────────────────────────────────┐
│  FastAPI (backend 容器)                                          │
│  ├─ API 层：inputs / drafts / bills / merchants / health         │
│  ├─ Pipeline：extract → validate → clarify → datasource → draft │
│  ├─ Job Worker：DB 队列，失败重试、断点续跑                       │
│  └─ LLM Client：硅基流动（文本 + 视觉），超时/重试/JSON 校验      │
└──────┬───────────────────────────────┬──────────────────────────┘
       │                               │
┌──────▼─────────────┐        ┌────────▼─────────────┐
│ PostgreSQL 16      │        │ 本地目录 data/uploads │
│ 输入/草稿/账单/     │        │ 截图持久化 (volume)   │
│ 澄清/轨迹/数据源    │        └──────────────────────┘
└────────────────────┘
```

---

## 4. 数据模型（核心表）

- `inputs`：原始输入（text/image）、状态、失败步骤/原因、时间戳
- `images`：文件元数据（sha256、路径、尺寸、mime）
- `drafts`：草稿（金额/日期/商户/类别/备注、`field_sources`、`confidence`、`warnings`、`suggestions`、`duplicate_candidates`、`conflict`、状态）
- `clarifications`：澄清问答（字段、问题、原因、状态、回答、轮次）
- `bills`：正式账单（`draft_id` 唯一，保证幂等）
- `trace_events`：处理轨迹（step/status/message/payload/耗时）
- `datasource_calls`：数据源调用（source/status/req/resp/error/latency）
- `merchants`：商户目录（标准名、别名数组、默认类别、置信度）
- `jobs`：后台任务队列（kind/status/attempts/run_after）
- `idempotency_keys`：提交/确认幂等

### 状态机

```
input:   pending → processing → (needs_clarification | ready_for_review | failed)
         needs_clarification → processing (补充后) → ...
         failed → processing (重试)
draft:   extracting → needs_clarification → ready_for_review → confirmed | rejected
           ↑___________回答/重试___________|
bill:    由 draft 确认生成，一条 draft 至多一条 bill
```

---

## 5. API 设计（`/api/v1`）

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/inputs` | 文本输入，创建并触发处理 |
| POST | `/inputs/upload` | 截图上传（multipart），创建并触发处理 |
| GET | `/inputs` | 列表（状态、类型、时间） |
| GET | `/inputs/{id}` | 详情：草稿、澄清、轨迹、数据源调用 |
| POST | `/inputs/{id}/retry` | 从失败步骤重试 |
| POST | `/clarifications/{id}/answer` | 回答澄清（含"不知道"） |
| POST | `/clarifications/{id}/cancel` | 取消澄清 |
| GET | `/drafts` | 草稿列表（按状态过滤） |
| GET | `/drafts/{id}` | 草稿详情（来源/警告/重复/建议） |
| PATCH | `/drafts/{id}` | 编辑草稿（记录 user 来源） |
| POST | `/drafts/{id}/confirm` | 确认入账（幂等 + 并发安全） |
| POST | `/drafts/{id}/reject` | 拒绝 |
| POST | `/drafts/{id}/datasources/{source}/retry` | 单数据源重试 |
| GET | `/bills` | 正式账单列表 |
| GET | `/merchants?q=` | 商户目录查询（前端展示用） |
| GET | `/health` | 健康检查（DB + LLM 配置） |

---

## 6. 关键实现策略

1. **结构化抽取**：严格 JSON schema 提示词 → `response_format=json_object` → Pydantic 校验；失败重试 2 次，仍失败则落 `failed` 并保留原始输出。
2. **澄清规划器（确定性）**：优先级 冲突 > 关键字段缺失 > 非关键字段缺失；每次只问一个字段；已 answered/unknown 不再问；"不知道"按关键性分流。
3. **冲突处理**：用户值与抽取值不一致 → 生成 `conflict` 澄清，必须明确"使用哪个值"后才落库。
4. **数据源**：`duplicate_check`（金额 ±0.01、日期 ±3 天、商户归一化相似）+ `merchant_catalog`（标准名/别名/ILIKE/相似度）；两源并行、独立记录、独立重试；结果只影响建议与警告。
5. **幂等**：草稿 `(input_id, seq)` upsert；确认时 `SELECT ... FOR UPDATE` + `bills.draft_id UNIQUE`，重复请求返回同一账单。
6. **断点续跑**：`inputs.failure_step` + job 重试；已成功的抽取结果复用，避免重复调用与重复草稿。
7. **可追溯**：所有步骤写 `trace_events`，前端时间轴 + 数据源面板展示。

---

## 7. 前端页面

- **工作台 `/`**：文本输入、截图拖拽上传（预览）、原始输入列表（类型/状态/时间）、轮询刷新
- **输入详情 `/inputs/:id`**：状态步骤条、草稿卡片、澄清对话（含"不知道/取消"）、数据源调用面板（失败可重试）、追溯时间轴
- **审核台 `/review`**：待审草稿列表、字段编辑（金额/日期/商户/类别/备注）、来源徽标、警告/疑似重复/商户建议、确认/拒绝
- **账单 `/bills`**：正式账单表格 + 汇总
- 全局：侧边导航、Toast 错误提示、空状态、加载骨架

---

## 8. 部署与 CI/CD

### 运行拓扑

```
GitHub (main push)
   │  GitHub Actions: lint/test/build
   ├─ build & push → ghcr.io/ayfwq/min-ledger-{backend,web}:<sha>
   └─ ssh deploy → /opt/min-ledger
                    docker compose pull && up -d
                    alembic upgrade head
                    curl /health 验证
```

### 服务器前置

- 安装 Docker + Compose 插件
- 创建 `/opt/min-ledger`，放入 `.env`（DB 密码、`SILICONFLOW_API_KEY`、`APP_PASSWORD`）
- GitHub Secrets：`SSH_HOST`、`SSH_USER`、`SSH_KEY`、`SSH_PORT`（可选）、`GHCR` 用 `GITHUB_TOKEN`

### 本地开发

```bash
docker compose -f docker-compose.dev.yml up -d postgres
cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload
cd frontend && pnpm install && pnpm dev
```

---

## 9. 里程碑

| 阶段 | 交付物 |
|------|--------|
| M1 | 仓库骨架、DB 模型与迁移、配置 |
| M2 | LLM 抽取 + 流水线 + 数据源 |
| M3 | 澄清/冲突/审核/幂等 API |
| M4 | Vue 前端四页面 |
| M5 | Docker/Compose/Nginx + 本地端到端验证 |
| M6 | GitHub Actions CI/CD + 部署文档 |
| M7 | 服务器上线（待 SSH 信息） |

---

## 10. 风险与对策

| 风险 | 对策 |
|------|------|
| LLM 输出不稳定/超时 | JSON 校验 + 重试 + 失败落库 + 手动重试 |
| 截图识别不准 | 低置信字段标记，关键字段缺失强制澄清 |
| 并发确认重复入账 | DB 唯一约束 + 行锁 + 幂等键 |
| 服务器资源小 | 镜像体积优化（多阶段构建）、可选单容器部署 |
| API Key 泄露 | `.env` 不入库、GitHub Secrets、日志脱敏；**建议轮换已粘贴的 key** |
| 重启丢任务 | DB 任务队列，启动时恢复 pending/running 任务 |
