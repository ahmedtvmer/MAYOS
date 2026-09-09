FROM python:3.12-slim

WORKDIR /app

# Install system dependencies (SQLite, OpenMP runtime for CPU inference)
RUN apt-get update && apt-get install -y --no-install-recommends \
    sqlite3 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install UV binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy ONLY requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install prebuilt llama-cpp-python wheel with AVX2 CPU acceleration
RUN uv pip install --system \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu \
    llama-cpp-python

# Install remaining project dependencies into system Python
RUN uv pip install --system -r requirements.txt

# Copy application source code
COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]