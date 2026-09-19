#!/usr/bin/env bash
# Run as the ordinary Ubuntu SSH user after copying the repository.
set -euo pipefail

if [[ "$(uname -m)" != "x86_64" ]]; then
  echo "Use an x86_64 EC2 instance: the benchmark task images are amd64." >&2
  exit 1
fi
sudo apt-get update
sudo apt-get install -y ca-certificates curl git rsync tmux docker.io docker-compose-v2 docker-buildx
sudo systemctl enable --now docker
sudo usermod -aG docker "$(id -un)"
docker compose version
docker buildx version

if ! command -v uv >/dev/null 2>&1; then
  installer="$(mktemp)"
  trap 'rm -f "$installer"' EXIT
  curl --proto '=https' --tlsv1.2 -LsSf https://astral.sh/uv/install.sh -o "$installer"
  sh "$installer"
fi
export PATH="$HOME/.local/bin:$PATH"
uv python install 3.12
uv sync --locked --python 3.12
echo "Setup complete. Log out and back in so the docker group applies."
echo "Then: docker info && uv run stbench-research doctor"
