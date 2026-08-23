#!/bin/bash
set -e # 遇到错误自动退出脚本

echo "=== [1/4] 开始拉取 GitHub 最新代码 ==="
git fetch --all
git reset --hard origin/main # 强制同步远程主分支

echo "=== [2/4] 开始重新构建 Docker 镜像 ==="
docker compose build --no-cache

echo "=== [3/4] 启动/更新容器 ==="
docker compose up -d --remove-orphans

echo "=== [4/4] 清理悬空镜像与无用缓存 ==="
docker image prune -f

echo "=== 更新完成！当前服务状态： ==="
docker compose ps

# 首次运行前赋予脚本可执行权限：chmod +x update.sh
