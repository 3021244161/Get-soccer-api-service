# Linux 部署教程

## 1. 适用范围

本教程用于部署 `football-api-service` 发布目录，对应系统为：

- Ubuntu 22.04 / Debian 12 / CentOS Stream 9 等常见 Linux 发行版
- 已联网，可拉取 Docker 镜像
- 服务器至少 `2C4G`，建议 `4C8G`

本服务包含三部分：

- `Redis`：缓存与版本存储
- `API`：对外提供 REST + JSON 接口
- `Scheduler`：后台定时刷新抓取任务

## 2. 发布目录说明

交付目录结构如下：

```text
football-api-service/
  app/
  docs/
    api/
      接口文档.md
  scripts/
    football_all_modules_once_scraper.py
  output/
  .env.example
  docker-compose.yml
  Dockerfile
  requirements.txt
  linux部署教程.md
```

部署时只需要这份目录，不需要原开发项目中的测试结果、调试文件和历史样本。

## 3. 安装 Docker

如果服务器尚未安装 Docker，可按以下方式安装。

### Ubuntu / Debian

```bash
sudo apt update
sudo apt install -y docker.io docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
docker --version
docker compose version
```

### CentOS Stream / Rocky / AlmaLinux

```bash
sudo dnf install -y docker docker-compose-plugin
sudo systemctl enable docker
sudo systemctl start docker
docker --version
docker compose version
```

## 4. 上传目录

将整个 `football-api-service` 上传到服务器，例如：

```bash
scp -r football-api-service user@your-server:/opt/
```

登录服务器后进入目录：

```bash
cd /opt/football-api-service
```

## 5. 配置环境变量

先复制环境模板：

```bash
cp .env.example .env
```

编辑 `.env`：

```bash
vim .env
```

建议至少确认以下配置：

```env
APP_NAME=Football Lottery API
APP_ENV=production
APP_HOST=0.0.0.0
APP_PORT=8000
LOG_LEVEL=INFO

REDIS_URL=redis://redis:6379/0
API_KEYS=replace-with-your-prod-api-key

FAST_REFRESH_INTERVAL_SECONDS=720
SLOW_REFRESH_INTERVAL_SECONDS=7200
REFRESH_LOCK_TTL_SECONDS=1800
CACHE_KEEP_VERSIONS=3
REDIS_KEY_PREFIX=lottery

PLAYWRIGHT_HEADLESS=true
RUN_SCHEDULER_IN_API=false
SCHEDULER_RUN_ON_STARTUP=true

SOURCE_URL=https://kt.59itou.com/2/user/12/shop/details/result_xcpmjW.html?id=54156441&reg_channel_type=kdcode_c&station_uuid=329640eji8qu1m1653302035
STATION_USER_ID=54156441
STATION_UUID=329640eji8qu1m1653302035
```

配置说明：

- `API_KEYS`：多个 key 用逗号分隔
- `REDIS_URL`：Docker Compose 默认使用内部 Redis 服务
- `RUN_SCHEDULER_IN_API=false`：推荐关闭 API 内嵌调度器，使用独立 `scheduler` 容器
- `SOURCE_URL / STATION_USER_ID / STATION_UUID`：抓取目标站点参数，支持按环境修改

## 6. 启动服务

在项目根目录执行：

```bash
docker compose up -d --build
```

查看容器状态：

```bash
docker compose ps
```

正常情况下应看到三个服务：

- `redis`
- `api`
- `scheduler`

## 7. 查看日志

查看 API 日志：

```bash
docker compose logs -f api
```

查看调度器日志：

```bash
docker compose logs -f scheduler
```

查看 Redis 日志：

```bash
docker compose logs -f redis
```

## 8. 首次健康检查

### 8.1 健康检查

```bash
curl http://127.0.0.1:8000/health
```

期望返回：

- `service_status = ok`
- `redis_status = ok`

### 8.2 刷新状态

```bash
curl -H "X-API-Key: replace-with-your-prod-api-key" \
  http://127.0.0.1:8000/api/v1/admin/refresh/status
```

期望返回：

- `status = idle` 或 `running`
- `active_version` 有值
- `cache_status = fresh`

### 8.3 全量查询

```bash
curl -H "X-API-Key: replace-with-your-prod-api-key" \
  "http://127.0.0.1:8000/api/v1/matches?include_matches=true&page=1&page_size=500&debug=false"
```

## 9. 常用运维命令

重启服务：

```bash
docker compose restart
```

停止服务：

```bash
docker compose down
```

重新构建并启动：

```bash
docker compose up -d --build
```

只重启调度器：

```bash
docker compose restart scheduler
```

## 10. 开放公网访问

生产环境建议使用 `Nginx` 反向代理，不建议长期依赖 `ngrok`。

示例 Nginx 配置：

```nginx
server {
    listen 80;
    server_name your-domain.example.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

重载 Nginx：

```bash
sudo nginx -t
sudo systemctl reload nginx
```

## 11. 开机自启

Docker 服务已自启时，容器通常可随 Docker 恢复。

如需更明确的开机启动控制，可创建 `systemd` 服务：

```ini
[Unit]
Description=Football API Service
Requires=docker.service
After=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=/opt/football-api-service
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=multi-user.target
```

保存为：

`/etc/systemd/system/football-api.service`

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable football-api
sudo systemctl start football-api
sudo systemctl status football-api
```

## 12. 常见问题

### 12.1 `api` 容器正常但接口无数据

排查顺序：

1. 看 `scheduler` 日志是否持续报错
2. 调用 `/api/v1/admin/refresh/status` 看 `last_error`
3. 确认目标站点参数是否正确
4. 确认服务器网络能访问目标站点与相关接口

### 12.2 Redis 连接失败

检查：

```bash
docker compose ps
docker compose logs redis
```

并确认 `.env` 中：

```env
REDIS_URL=redis://redis:6379/0
```

### 12.3 Playwright 抓取失败

先看：

```bash
docker compose logs -f api
docker compose logs -f scheduler
```

如果是源站结构变更，需要更新抓取脚本后重新构建：

```bash
docker compose up -d --build
```

## 13. 交付后建议

- 将 `API_KEYS` 改成正式生产 key，不要继续使用开发 key
- 使用固定域名 + Nginx + HTTPS
- 定期备份 `output/` 中最新快照
- 监控 `/health` 和 `/api/v1/admin/refresh/status`
- 如果要多客户使用，建议按客户拆分 API Key
