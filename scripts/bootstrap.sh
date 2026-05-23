#!/usr/bin/env bash
# scripts/bootstrap.sh
# One-shot bootstrap: install deps, start Postgres, migrate.
#
# Usage:  ./scripts/bootstrap.sh
#
# Idempotent — safe to re-run.

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

green() { printf "\033[32m%s\033[0m\n" "$*"; }
red()   { printf "\033[31m%s\033[0m\n" "$*"; }
ylw()   { printf "\033[33m%s\033[0m\n" "$*"; }

# 1) Python version check
if ! command -v python3 &>/dev/null; then
  red "python3 not found. On Debian 13: sudo apt install python3 python3-venv python3-dev"
  exit 1
fi
PYV=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
if [[ "$(printf '%s\n' "3.11" "$PYV" | sort -V | head -n1)" != "3.11" ]]; then
  red "Python 3.11+ required (found $PYV)."
  exit 1
fi
green "✔ python $PYV"

# 2) Docker check
if ! command -v docker &>/dev/null; then
  red "docker not found. On Debian 13: sudo apt install docker.io docker-compose-v2"
  exit 1
fi
if ! docker compose version &>/dev/null; then
  red "'docker compose' (v2) not found. Try 'sudo apt install docker-compose-v2'."
  exit 1
fi
green "✔ docker $(docker --version | awk '{print $3}' | tr -d ,)"

# 3) Virtualenv
if [[ ! -d .venv ]]; then
  ylw "→ creating .venv"
  python3 -m venv .venv
fi
green "✔ .venv"

# 4) Install
ylw "→ installing dependencies (may take a few minutes)"
.venv/bin/pip install --upgrade pip wheel setuptools >/dev/null
.venv/bin/pip install -e ".[dev]"
green "✔ dependencies installed"

# 5) .env
if [[ ! -f .env ]]; then
  cp .env.example .env
  green "✔ wrote .env (copied from .env.example)"
else
  green "✔ .env present (kept)"
fi

# 6) Start Postgres
ylw "→ starting postgres"
docker compose up -d postgres
until docker compose exec -T postgres pg_isready -U flowprov -d flowprov >/dev/null 2>&1; do
  sleep 1
done
green "✔ postgres ready on localhost:5433"

# 7) Migrate
ylw "→ applying migrations"
.venv/bin/alembic upgrade head
green "✔ schema is up to date"

# 8) Done
cat <<'EOF'

  next steps:

    Terminal A:   make api          # starts the dashboard at http://localhost:8000
    Terminal B:   make demo         # seeds 5 flows with realistic baseline executions
                  make demo-drift   # injects a prompt regression to fire drift alerts

EOF
