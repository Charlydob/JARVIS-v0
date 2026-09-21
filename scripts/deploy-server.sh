#!/usr/bin/env bash
set -Eeuo pipefail

expected_dir="/opt/jarvis"
expected_remote="github.com/Charlydob/JARVIS-v0"

if [[ "$(pwd -P)" != "$expected_dir" ]]; then
  echo "Refusing to deploy outside $expected_dir" >&2
  exit 1
fi

if [[ "$(git branch --show-current)" != "main" ]]; then
  echo "Refusing to deploy a branch other than main" >&2
  exit 1
fi

remote_url="$(git remote get-url origin)"
if [[ "$remote_url" != *"$expected_remote"* ]]; then
  echo "Unexpected git remote: $remote_url" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Refusing to overwrite local changes in $expected_dir" >&2
  exit 1
fi

git fetch --prune origin main
git merge --ff-only origin/main
export JARVIS_BUILD_SHA="$(git rev-parse HEAD)"
export JARVIS_VERSION="$(tr -d '[:space:]' < VERSION)"
docker compose config --quiet
docker compose up -d --build gateway web

for attempt in {1..20}; do
  if curl --fail --silent --show-error http://127.0.0.1:8088/api/health >/dev/null; then
    docker compose ps gateway web
    exit 0
  fi
  sleep 3
done

docker compose ps gateway web
docker compose logs --tail=100 gateway web
exit 1
