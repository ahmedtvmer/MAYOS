FROM nvidia/cuda:12.4.1-runtime-ubuntu22.04

WORKDIR /app

# Prevent interactive prompts during apt package installation
ENV DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# Install Python 3.12, build tools, and SQLite dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    curl \
    sqlite3 \
    libgomp1 \
    build-essential \
    tzdata \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-dev \
    python3.12-venv \
    && rm -rf /var/lib/apt/lists/*

# Bootstrap pip for Python 3.12 and configure default python symlinks
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.12 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.12 1

# Install UV binary
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# NVIDIA Container runtime flags
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    N_GPU_LAYERS=-1 \
    EMBEDDING_DEVICE=cuda

COPY requirements.txt .

# Install CUDA 12.4 prebuilt wheel for llama-cpp-python
RUN uv pip install --system \
    --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cu124 \
    llama-cpp-python

RUN uv pip install --system -r requirements.txt

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]