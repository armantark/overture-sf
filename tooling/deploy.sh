#!/usr/bin/env bash
# Build the container, push it to Docker Hub, and create or update the Koyeb service.
#
# Koyeb's free tier deploys a prebuilt image, which means the whole release is one command
# and needs no GitHub repository or connected build pipeline.
#
#   ./tooling/deploy.sh            # build, push, deploy
#   ./tooling/deploy.sh --no-build # redeploy the image already on Docker Hub
set -euo pipefail

IMAGE="${IMAGE:-armantark/overture-sf}"
TAG="${TAG:-latest}"
APP="${APP:-overture-sf}"
SERVICE="${SERVICE:-web}"
REGION="${REGION:-was}"
INSTANCE="${INSTANCE:-free}"

cd "$(dirname "$0")/.."

if [[ "${1:-}" != "--no-build" ]]; then
  echo "==> Building ${IMAGE}:${TAG}"
  # Koyeb runs amd64. Building on an Apple Silicon machine without this produces an arm64
  # image that pushes fine and then fails to start with an exec format error.
  docker build --platform linux/amd64 -t "${IMAGE}:${TAG}" .

  echo "==> Pushing ${IMAGE}:${TAG}"
  docker push "${IMAGE}:${TAG}"
fi

if koyeb services describe "${APP}/${SERVICE}" >/dev/null 2>&1; then
  echo "==> Updating existing service ${APP}/${SERVICE}"
  koyeb services update "${APP}/${SERVICE}" \
    --docker "${IMAGE}:${TAG}" \
    --instance-type "${INSTANCE}"
else
  echo "==> Creating service ${APP}/${SERVICE}"
  koyeb app create "${APP}" >/dev/null 2>&1 || true
  koyeb services create "${SERVICE}" \
    --app "${APP}" \
    --docker "${IMAGE}:${TAG}" \
    --instance-type "${INSTANCE}" \
    --regions "${REGION}" \
    --ports 8000:http \
    --routes /:8000 \
    --checks 8000:http:/api/health
fi

echo "==> Waiting for the deployment to go healthy"
for _ in $(seq 1 60); do
  status=$(koyeb services describe "${APP}/${SERVICE}" -o json 2>/dev/null \
           | python3 -c 'import sys,json; print(json.load(sys.stdin).get("status",""))' 2>/dev/null || echo "")
  echo "    status: ${status:-unknown}"
  [[ "$status" == "HEALTHY" ]] && break
  sleep 10
done

koyeb apps describe "${APP}" -o json 2>/dev/null \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); print("URL: https://" + (d.get("domains") or [{}])[0].get("name",""))' 2>/dev/null \
  || koyeb apps list
