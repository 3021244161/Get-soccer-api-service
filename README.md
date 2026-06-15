# Football API Service

面向足球数据抓取、缓存与接口服务的一体化交付项目。

本系统围绕以下四个足球模块提供统一查询接口：

- `竞彩足球`
- `北京单场`
- `足球14场`
- `胜负过关`

系统采用 `爬虫 -> Redis -> API` 的结构运行，适合部署在 Linux 服务器，通过缓存对外提供稳定的 REST + JSON 接口服务。

## 1. 系统说明

本项目的目标是把目标站点中的足球赛事数据抓取下来，并以统一的 API 形式稳定对外输出。

当前已支持的抓取范围包括：

- 列表页赛事基础信息
- `战绩`
- `综合实力 -> 查看详细数据`
- `阵容`
- `欧指`
- `亚指`

当前系统已具备以下能力：

- 四模块统一字段输出
- Redis 缓存与版本化存储
- 双频刷新策略
- API Key 鉴权
- Docker Compose 部署
- Linux 服务器部署

## 2. 刷新策略

系统当前采用双频刷新：

- 快刷新：每 `12` 分钟刷新赔率、欧指、亚指
- 慢刷新：每 `2` 小时刷新战绩、查看详细数据、阵容等慢字段

对外接口返回的仍然是一条完整比赛对象，不需要调用方自行做快慢字段拼接。

## 3. 适用读者

本 README 同时面向两类读者：

- 部署方：快速了解如何启动服务、配置环境变量、检查运行状态
- 使用方：快速了解接口能力、鉴权方式、文档位置和调用入口

## 4. 快速开始

### 4.1 环境要求

推荐环境：

- Linux 服务器
- Docker
- Docker Compose

如需本地运行，也可使用 Windows 或 Linux，但正式部署推荐 Linux。

### 4.2 配置环境变量

复制模板：

```bash
cp .env.example .env
```

至少确认以下配置：

```env
REDIS_URL=redis://redis:6379/0
API_KEYS=replace-with-your-api-key
FAST_REFRESH_INTERVAL_SECONDS=720
SLOW_REFRESH_INTERVAL_SECONDS=7200
PLAYWRIGHT_HEADLESS=true
RUN_SCHEDULER_IN_API=false
SCHEDULER_RUN_ON_STARTUP=true
SOURCE_URL=...
STATION_USER_ID=...
STATION_UUID=...
```

### 4.3 启动服务

```bash
docker compose up -d --build
```

### 4.4 查看状态

```bash
docker compose ps
docker compose logs -f api
docker compose logs -f scheduler
```

### 4.5 健康检查

```bash
curl http://127.0.0.1:8000/health
```

### 4.6 刷新状态

```bash
curl -H "X-API-Key: replace-with-your-api-key" \
  http://127.0.0.1:8000/api/v1/admin/refresh/status
```

## 5. 接口使用

### 5.1 鉴权方式

除 `/health` 外，其余核心接口均使用 API Key 鉴权。

请求头：

```text
X-API-Key: your-api-key
```

### 5.2 常用接口

- `GET /health`：健康检查
- `GET /api/v1/meta`：服务元信息
- `GET /api/v1/matches`：四模块聚合查询
- `GET /api/v1/modules/{module_code}`：单模块查询
- `GET /api/v1/modules/{module_code}/matches/{match_id2}`：单场详情
- `POST /api/v1/admin/refresh`：手动触发刷新
- `GET /api/v1/admin/refresh/status`：刷新状态查询

### 5.3 全量查询示例

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/v1/matches?include_matches=true&page=1&page_size=500&debug=false"
```

### 5.4 单场详情示例

```bash
curl -H "X-API-Key: your-api-key" \
  "http://127.0.0.1:8000/api/v1/modules/jczq/matches/2589459?debug=false"
```

## 6. 接口文档

完整接口定义见：

- [`docs/api/接口文档.md`](file:///e:/ChangeJob/api%E5%B0%81%E8%A3%85(680)/delivery/football-api-service/docs/api/%E6%8E%A5%E5%8F%A3%E6%96%87%E6%A1%A3.md)

部署说明见：

- [`linux部署教程.md`](file:///e:/ChangeJob/api%E5%B0%81%E8%A3%85(680)/delivery/football-api-service/linux%E9%83%A8%E7%BD%B2%E6%95%99%E7%A8%8B.md)

## 7. 项目结构

```text
football-api-service/
  app/                                  # API、缓存、调度、查询、刷新核心代码
  docs/api/接口文档.md                   # 接口文档
  scripts/football_all_modules_once_scraper.py
                                        # 抓取核心脚本
  output/                               # 运行时输出目录
  .env.example                          # 环境变量模板
  Dockerfile                            # 镜像构建文件
  docker-compose.yml                    # 部署入口
  linux部署教程.md                      # Linux 部署教程
  README.md                             # 项目首页说明
```

## 8. 部署建议

正式环境建议：

- 使用 Linux 服务器部署
- 使用 Docker Compose 运行 `redis + api + scheduler`
- 使用 Nginx 做反向代理
- 使用固定域名和 HTTPS
- 使用独立生产 API Key

不建议长期依赖：

- 临时公网隧道
- 开发 key
- 手工直接运行单进程脚本

## 9. 注意事项

- `.env` 不应提交到代码仓库
- `output/` 目录需要保留写权限
- 当上游站点结构变化时，抓取脚本可能需要同步调整
- 如果需要切换抓取目标站点参数，可直接修改 `.env` 中的站点相关变量，不需要改代码

## 10. 交付说明

本目录是精简后的发布目录，已去除以下非交付内容：

- 测试结果 JSON
- 调试日志
- 临时脚本
- 历史样本文件
- 本地实验性文件

因此该目录适合：

- 上传到私有 GitHub 仓库
- 打包交付部署方
- 直接作为服务器部署源目录使用
