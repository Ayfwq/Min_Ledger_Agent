# 部署指南

目标拓扑：单台 Linux 服务器上以 Docker Compose 运行 **PostgreSQL + FastAPI + Nginx(Vue)**，由 GitHub Actions 构建镜像并 SSH 部署。

```
用户 ──HTTPS──> Nginx(web) ──/api──> FastAPI(backend) ──> PostgreSQL
                     │
                     └── 静态资源 (Vue SPA)
```

---

## 0. 前置条件

- 一台 Linux 服务器（Ubuntu 22.04 / Debian 12 推荐，1C2G 起步）
- 可 SSH 登录，具备 sudo 权限
- GitHub 仓库：`https://github.com/Ayfwq/Min_Ledger_Agent`
- 硅基流动 API Key

---

## 1. 服务器初始化

把初始化脚本上传到服务器并执行：

```bash
scp deploy/server-bootstrap.sh deploy/.env.example user@<server>:/tmp/
ssh user@<server>
sudo bash /tmp/server-bootstrap.sh
# 或手动：
curl -fsSL https://get.docker.com | sh
mkdir -p /opt/min-ledger
```

把 `deploy/.env.example` 复制为 `/opt/min-ledger/.env` 并填写：

```bash
cd /opt/min-ledger
cp .env.example .env
vim .env
```

必须修改：

| 变量 | 说明 |
|------|------|
| `POSTGRES_PASSWORD` | 强随机密码（不要含 `@ : /` 等会破坏 URL 的字符） |
| `SILICONFLOW_API_KEY` | 硅基流动 Key |
| `APP_PASSWORD` | 访问密码（强烈建议） |
| `ALLOWED_ORIGINS` | 站点域名，如 `https://ledger.example.com` |
| `HTTP_PORT` | 对外端口，默认 80 |

> 数据库连接串由 compose 自动拼接，无需手写 `DATABASE_URL`。

---

## 2. GitHub Secrets

仓库 → Settings → Secrets and variables → Actions：

| Secret | 必填 | 说明 |
|--------|------|------|
| `SSH_HOST` | ✅ | 服务器 IP / 域名 |
| `SSH_USER` | ✅ | SSH 用户（需在 docker 组） |
| `SSH_KEY` | 二选一 | 私钥（PEM，含 BEGIN/END 行） |
| `SSH_PASSWORD` | 二选一 | 服务器登录密码（与 `SSH_KEY` 填一个即可） |
| `SSH_PORT` | 可选 | 默认 22 |
| `GHCR_PAT` | 可选 | 拉取私有镜像用的 PAT（`read:packages`）；镜像已公开时不需要 |

> 用密码登录服务器时只填 `SSH_PASSWORD`，不要同时填 `SSH_KEY`。
> 推荐方式仍是密钥；密码方式适合临时/测试服务器。

生成部署密钥：

```bash
ssh-keygen -t ed25519 -C "min-ledger-deploy" -f deploy_key -N ""
# 公钥追加到服务器：~/.ssh/authorized_keys
# 私钥内容粘贴到 GitHub Secret SSH_KEY
```

镜像仓库为 `ghcr.io/ayfwq/min-ledger-backend` 与 `ghcr.io/ayfwq/min-ledger-web`。
首次推送后，可在 GitHub Packages 中把两个包设为 **Public**，这样服务器无需 `GHCR_PAT` 即可拉取。

---

## 3. 首次部署

```bash
git push origin main
```

Actions 会：

1. `backend`：`uv sync` → `ruff` → `pytest`；
2. `frontend`：`npm ci` → `npm run build`；
3. `docker`：构建两个镜像做冒烟验证；
4. `deploy`：
   - 构建并推送 `ghcr.io/ayfwq/min-ledger-{backend,web}:<sha>` 与 `:latest`
   - 通过 `scp` 上传 `docker-compose.yml`、`deploy.sh`
   - SSH 执行 `deploy.sh <sha>`：`docker compose pull && up -d`，等待健康检查，失败自动回滚

首次部署前，请确认 `/opt/min-ledger/.env` 已存在，否则 `deploy.sh` 会直接退出。

也可以手动触发：Actions → Deploy → Run workflow（可指定 tag）。

---

## 4. 验证

```bash
curl -s http://<server>/api/v1/health
# {"status":"ok","database":"ok","llm_configured":true,"queue":{"queued":0,"running":0}}

docker compose -f /opt/min-ledger/docker-compose.yml ps
docker compose -f /opt/min-ledger/docker-compose.yml logs -f backend
```

浏览器打开 `http://<server>/`，输入一句话或上传截图，走完「识别 → 澄清 → 审核 → 入账」。

---

## 5. 回滚

`deploy.sh` 会记录上一次成功的 tag 到 `/opt/min-ledger/.last_good_tag`。
健康检查失败时自动回滚到该 tag。手动回滚：

```bash
cd /opt/min-ledger
./deploy.sh $(cat .last_good_tag)
```

---

## 6. HTTPS（可选但推荐）

用 Caddy 反代 80/443 最简单：

```caddyfile
ledger.example.com {
    reverse_proxy 127.0.0.1:80
}
```

然后 `HTTP_PORT=8080`（compose 只监听本机回环可改为 `127.0.0.1:8080:80`），避免直接暴露 80。
或使用 Nginx + certbot 签发证书。

---

## 7. 数据与备份

| 数据 | 位置 |
|------|------|
| PostgreSQL | named volume `min-ledger_pgdata` |
| 截图 | named volume `min-ledger_uploads` |

备份：

```bash
docker exec -t $(docker compose ps -q db) pg_dump -U ledger ledger | gzip > backup-$(date +%F).sql.gz
docker run --rm -v min-ledger_uploads:/data -v $PWD:/backup alpine \
  tar czf /backup/uploads-$(date +%F).tar.gz -C /data .
```

---

## 8. 常见问题

| 现象 | 处理 |
|------|------|
| `unauthorized` 拉取镜像 | 配置 `GHCR_PAT`，或在 Packages 设为 Public |
| 健康检查失败 | `docker compose logs backend`；常见为 `.env` 缺 Key、数据库密码含特殊字符 |
| 页面 404 | Nginx 未命中 `try_files`，确认镜像为最新 `min-ledger-web` |
| 上传大图失败 | 调整 `.env` 的 `MAX_UPLOAD_MB` 与 Nginx `client_max_body_size` |
| LLM 调用超时 | 调大 `LLM_TIMEOUT_SECONDS`；服务器在境外可设置 `LLM_PROXY` |
| 端口被占用 | 修改 `.env` 的 `HTTP_PORT` 后重新 `./deploy.sh` |

---

## 9. 手动部署（不使用 Actions）

```bash
# 本地构建并推送
docker build -t ghcr.io/ayfwq/min-ledger-backend:manual ./backend
docker build -t ghcr.io/ayfwq/min-ledger-web:manual ./frontend
docker push ghcr.io/ayfwq/min-ledger-backend:manual
docker push ghcr.io/ayfwq/min-ledger-web:manual

# 服务器
cd /opt/min-ledger
./deploy.sh manual
```
