# 验收对照表

> 把作业 PDF 的每一条要求映射到具体实现与可复现的验证方式。

## 一、自动化测试

```bash
cd backend
uv run ruff check app tests
uv run pytest -q          # 21 passed
```

| 用例 | 覆盖要求 |
|------|----------|
| `test_health` | 服务/数据库健康、版本号 |
| `test_multi_transaction_extraction` | 一条输入多笔账单、非关键字段缺失只给警告 |
| `test_missing_amount_blocks_confirmation` | 金额缺失生成阻塞澄清，确认入账返回 409 |
| `test_answer_clarification_then_confirm_is_idempotent` | 补充后合并、来源标记为用户、重复确认只生成一条账单 |
| `test_conflict_requires_force_override` | 修改识别值必须二次确认（`value_conflict`） |
| `test_duplicate_detection_and_retry` | 查重命中历史账单、数据源调用留痕、单源重试 |
| `test_llm_failure_then_retry` | 模型失败落库、失败步骤、输入可重试 |
| `test_unknown_answer_keeps_blocking` | “不知道”记录状态且关键字段仍阻塞 |
| `test_low_confidence_merchant_gets_non_blocking_question` | 低置信商户触发非阻塞“识别是否正确”确认 |
| `test_image_upload_is_persisted` | 截图保存、来源标记为 `image` |
| `test_datasource_failure_does_not_block_draft` | 数据源失败不阻塞草稿、警告展示、重试后清除 |
| `test_auth` | 可选访问密码保护 |
| `test_confirm_closes_optional_clarifications` | 入账/拒绝后关闭未回答的可选澄清 |
| `test_input_list_exposes_latest_clarification` | 输入列表携带最新澄清问题 |
| `test_merchant_catalog_falls_back_to_description` | 商户缺失时用说明查询商户目录 |
| `test_parsing` | 金额/日期/商户归一化解析 |

## 二、浏览器端到端（Playwright）

```bash
# 先启动实例（二选一）
docker compose -f deploy/docker-compose.prod.yml up -d      # 或本地开发模式
BASE=http://127.0.0.1:18080 node tools/e2e_ui.cjs
```

覆盖：缺金额澄清 → 提交 → 确认入账；编辑识别值触发冲突弹窗 → 确认覆盖 → 拒绝；账单搜索；审核台状态筛选。

## 三、部署与并发验证（已实测）

| 验证 | 结果 |
|------|------|
| 全栈 Compose 启动（PG + API + Nginx） | `docker compose ps` 三个服务 healthy |
| Nginx 代理 API / 静态资源 / 截图 | `/api/v1/health` 200，`/uploads/<file>` 200 |
| 服务重启后数据仍可查 | 重启 backend 后输入/草稿/澄清/轨迹数量一致，截图仍 200 |
| 10 个并发确认请求 | 全部 200，仅生成 1 条账单（`tools/concurrent_confirm.py`） |
| `deploy.sh` 成功路径 | 发布 → 健康检查 → 记录 `.last_good_tag` |
| `deploy.sh` 失败回滚 | 坏镜像健康检查失败 → 自动回滚到上一 tag 并恢复健康 |
| GitHub Actions | CI / Deploy 均通过，镜像推送 GHCR |

## 四、作业要求逐条对照

| PDF 要求 | 实现位置 | 验证方式 |
|----------|----------|----------|
| 文本输入、多笔 | `services/llm.py` 提示词、`pipeline.build_drafts` | `test_multi_transaction_extraction` |
| 截图上传、预览、持久化 | `POST /inputs/upload`、`frontend Workbench`、uploads volume | `test_image_upload_is_persisted`、UI E2E |
| 文字 + 截图同时提交 | 统一输入框 `kind=mixed` | `test_mixed_text_and_image_input` |
| 图文冲突 → 歧义确认 | 模型 `ambiguous_fields` → 阻塞确认 | `test_ambiguous_critical_field_blocks_confirm_until_resolved` |
| 输入列表区分类型/状态/澄清/草稿 | `Workbench.vue`、`GET /inputs`（含最新追问） | UI + `test_input_list...` |
| 金额/日期/商户/类别/来源 | `models.Draft.field_sources`、`DraftCard.vue` | UI 来源徽标 |
| 关键字段缺失不可确认 | `ledger.confirm_draft` | `test_missing_amount_blocks_confirmation` |
| 非关键字段不编造 | `_sync_from_extraction` 只写模型返回值 | `compute_warnings` |
| 只阻塞不完整的那一笔 | 草稿级状态机 | `test_multi_transaction_extraction` |
| 多轮澄清、不重复问 | `ensure_clarification` + `clarifications` 表 | `test_answer_clarification...` |
| 歧义（低置信商户）主动确认 | `kind=ambiguous` + 「识别正确」按钮 | `test_low_confidence_merchant...` |
| 不知道/暂不提供 | `action=unknown` | `test_unknown_answer_keeps_blocking` |
| 冲突必须确认 | `_values_differ` + `force` | `test_conflict_requires_force_override`、UI 冲突弹窗 |
| 澄清可取消 | `POST /clarifications/{id}/cancel` | UI「取消澄清」 |
| 历史账单/草稿查重 | `datasources.check_duplicates` | `test_duplicate_detection_and_retry` |
| 商户目录标准化（商户或说明） | `datasources.lookup_merchant` + 30 条种子 | UI「商户目录建议」、`test_merchant_catalog...` |
| 数据源独立失败/重试 | `datasource_calls` + `/datasources/{source}/retry` | `test_datasource_failure...` |
| 疑似重复/低置信提示 | `compute_warnings`、`duplicate_candidates` | UI 黄色提示 |
| 审核编辑/确认/拒绝 | `Review.vue`、`ledger.py` | UI E2E |
| 重复确认只入账一次 | `bills.draft_id UNIQUE` + 行锁 | 并发实测 |
| 全链路追溯 | `trace_events`、`TraceTimeline.vue` | 详情页时间轴 |
| LLM 失败/格式异常 | `LLMError` + 重试 + 失败落库 | `test_llm_failure_then_retry` |
| 重启后可查 | PostgreSQL + volume | 重启实测 |
| 不能只用内存 | 全部落库 | — |

## 五、截图

| 页面 | 文件 |
|------|------|
| 工作台 | `docs/screenshots/workbench.png` |
| 处理详情 | `docs/screenshots/input-detail.png` |
| 审核台 | `docs/screenshots/review.png` |
| 正式账单 | `docs/screenshots/bills.png` |
