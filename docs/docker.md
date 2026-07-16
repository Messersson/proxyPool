# Docker 部署

## 使用 Docker 镜像

拉取并运行 Docker 镜像：

```console
docker pull jhao104/proxy_pool:latest

docker run --env DB_CONN=redis://:password@ip:port/0 -p 5010:5010 jhao104/proxy_pool:latest
```

`DB_CONN` 环境变量会覆盖 `setting.py` 中的数据库连接配置。如需鉴权可附加 `API_TOKEN`。

## 使用 docker-compose

项目根目录下的 `docker-compose.yml` 定义了 ProxyPool 和 Redis 两个服务：

```yaml
version: "3.8"
services:
  proxy_pool:
    build: .
    container_name: proxy_pool
    ports:
      - "5010:5010"
    depends_on:
      proxy_redis:
        condition: service_healthy
    environment:
      DB_CONN: "redis://@proxy_redis:6379/0"
    restart: unless-stopped
  proxy_redis:
    image: redis:7-alpine
    container_name: proxy_redis
    command: ["redis-server", "--save", "60", "1", "--loglevel", "warning"]
    volumes:
      - proxy_redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 10
    restart: unless-stopped
volumes:
  proxy_redis_data:
```

启动：

```console
docker-compose up -d
```

## 容器环境注意事项

在 Docker 容器中，建议使用前台模式启动服务：

```console
./proxy_pool.sh start --fg
```

Dockerfile 中的 ENTRYPOINT 配置：

```dockerfile
ENTRYPOINT ["tini", "--", "bash", "proxy_pool.sh", "start", "--fg"]
```

镜像基于 Alpine，已安装 `bash` 与 `tini`，避免入口脚本找不到 shell。
