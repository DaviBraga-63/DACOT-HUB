#!/usr/bin/env bash

# Build both parts of the Hub from the same checked-out Git revision. The
# FastAPI application serves frontend/build, so this must run before startup.
set -o errexit
set -o nounset
set -o pipefail

pushd frontend >/dev/null
yarn install --frozen-lockfile --production=false
yarn build
popd >/dev/null

python -m pip install -r backend/requirements.txt
