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
# {"status":"ok","version":"<commit>","database":"ok","llm_configured":true,"queue":{"queued":0,"running":0}}

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

## 5.1 80/443 已被其它项目占用

安全组只开放 80/443 时，不要停掉现有 Nginx。用独立端口 + 宿主机 Nginx 反代：

```bash
# 1) .env 里选择空闲端口
HTTP_PORT=8080

# 2) 宿主机 Nginx 增加一个 vhost（不会影响其它 server_name）
scp deploy/nginx-vhost.conf.example root@<server>:/etc/nginx/conf.d/min-ledger.conf
ssh root@<server> 'nginx -t && nginx -s reload'
```

没有域名时可用 `nip.io` 泛解析，例如 `ledger.47.111.128.185.nip.io`（自动解析到该 IP）。
把 vhost 中的 `server_name` 改成它即可通过 `http://ledger.47.111.128.185.nip.io/` 访问。

删除该文件并 `nginx -s reload` 即可完全撤销，不影响服务器上其它站点。

> Docker Hub 在大陆经常不可达：`.env` 里设置 `DB_IMAGE=docker.m.daocloud.io/library/postgres:16-alpine`。
> GHCR 拉取慢时设置 `IMAGE_REGISTRY=ghcr.nju.edu.cn`，部署脚本会自动改用该镜像代理。

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
| 备份文件 | `${APP_DIR}/backups`（默认保留 7 天） |

一键备份（数据库 + 截图）：

```bash
cd /opt/min-ledger
./backup.sh
# 或自定义：KEEP_DAYS=30 ./backup.sh
```

定时任务：

```cron
0 3 * * * cd /opt/min-ledger && ./backup.sh >> /var/log/ledger-backup.log 2>&1
```

恢复：

```bash
cd /opt/min-ledger
gunzip -c backups/db-20261111-030000.sql.gz | docker compose exec -T db psql -U ledger -d ledger
docker compose exec -T backend tar xzf - -C /app/data/uploads < backups/uploads-20261111-030000.tar.gz
```

---

## 8. 常见问题

| 现象 | 处理 |
|------|------|
| `unauthorized` 拉取镜像 | 配置 `GHCR_PAT`，或在 Packages 设为 Public |
| `permission denied` 连接 Docker | SSH 用户不在 docker 组：`sudo usermod -aG docker $USER` 后重新登录 |
| `exec format error` | 服务器是 ARM 架构，需要构建 `linux/arm64` 镜像（默认仅 amd64） |
| 健康检查失败 | `docker compose logs backend`；常见为 `.env` 缺 Key、数据库密码含特殊字符 |
| 页面 404 | Nginx 未命中 `try_files`，确认镜像为最新 `min-ledger-web` |
| 上传大图失败 | 调整 `.env` 的 `MAX_UPLOAD_MB` 与 Nginx `client_max_body_size` |
| LLM 调用超时 | 调大 `LLM_TIMEOUT_SECONDS`；服务器在境外可设置 `LLM_PROXY` |
| 端口被占用 | 修改 `.env` 的 `HTTP_PORT` 后重新 `./deploy.sh` |

---

## 9. 镜像拉取慢 / 无法访问 GHCR

大陆服务器访问 GHCR、Docker Hub 可能很慢，按情况选一种：

**A. 数据库镜像换源**（最快）：

```bash
# 在 .env 中
DB_IMAGE=docker.m.daocloud.io/library/postgres:16-alpine
```

**B. 推到其它镜像仓库**（阿里云 ACR / 腾讯 TCR）：

```bash
docker pull ghcr.io/ayfwq/min-ledger-backend:latest
docker tag  ghcr.io/ayfwq/min-ledger-backend:latest registry.cn-hangzhou.aliyuncs.com/<namespace>/min-ledger-backend:latest
docker push registry.cn-hangzhou.aliyuncs.com/<namespace>/min-ledger-backend:latest
# web 同理，然后在 .env 覆盖：
# BACKEND_IMAGE=registry.cn-hangzhou.aliyuncs.com/<namespace>/min-ledger-backend:latest
# WEB_IMAGE=registry.cn-hangzhou.aliyuncs.com/<namespace>/min-ledger-web:latest
```

**C. 离线镜像包**（完全不依赖仓库）：

```bash
# 有网络的机器
docker pull ghcr.io/ayfwq/min-ledger-backend:<tag>
docker pull ghcr.io/ayfwq/min-ledger-web:<tag>
docker save ghcr.io/ayfwq/min-ledger-backend:<tag> ghcr.io/ayfwq/min-ledger-web:<tag> | gzip > ledger-images.tar.gz
scp ledger-images.tar.gz user@server:/opt/min-ledger/

# 服务器
cd /opt/min-ledger
gunzip -c ledger-images.tar.gz | docker load
# .env 里设置 PULL_POLICY=missing
PULL_POLICY=missing SKIP_PULL=1 ./deploy.sh <tag>
```

> `postgres:16-alpine` 也需要在服务器上可用（`docker pull` 或同样离线导入）。

---

## 10. 手动部署（不使用 Actions）

```bash
# 本地构建并推送
docker build -t ghcr.io/ayfwq/min-ledger-backend:manual ./backend
docker build -t ghcr.io/ayfwq/min-ledger-web:manual ./frontend
docker push ghcr.io/ayfwq/min-ledger-backend:manual
docker push ghcr.io/ayfwq/min-ledger-web:manual

# 服务器
cd /opt/min-ledger\n./deploy.sh manual
```
