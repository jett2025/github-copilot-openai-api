FROM ghcr.io/astral-sh/uv:python3.12-alpine

# 安装系统依赖
RUN apk add --no-cache curl

WORKDIR /app

# 复制依赖文件
COPY pyproject.toml ./

# 安装依赖包（不包括当前项目）
RUN uv pip install --no-cache-dir --system \
    "aiohttp>=3.11.14" \
    "async-lru>=2.0.5" \
    "fastapi>=0.115.11" \
    "jinja2>=3.1.6" \
    "loguru>=0.7.3" \
    "uvicorn>=0.34.0"

# 复制项目文件
COPY api/ ./api/
COPY auth/ ./auth/
COPY templates/ ./templates/
COPY server.py ./

# 设置环境变量
ENV HOST=0.0.0.0
ENV PORT=8000
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/v1/models || exit 1

# 启动应用
CMD ["python", "server.py"] 