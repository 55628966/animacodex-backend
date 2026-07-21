#!/usr/bin/env bash
# Anima Codex 后端联调启动脚本(模型A)
# 端口 8901 写死, 供模型B前端联调; 只监听本机 127.0.0.1。
cd "$(dirname "$0")/.." || exit 1
exec ./.venv/bin/uvicorn api.main:app --host 127.0.0.1 --port 8901
