FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends bash git ripgrep jq ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /workspace
