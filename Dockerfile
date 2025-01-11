FROM python:3.11-slim
RUN pip install uv
WORKDIR /app

# deps
COPY pyproject.toml uv.lock* ./
ENV UV_PYTHON_PREFERENCE=only-system
RUN uv sync

# repo
COPY . .

# run
EXPOSE 8080
ENV PORT=8080
ENTRYPOINT ["uv", "run", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "$PORT"]
