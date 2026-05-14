#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASE_DIR="$ROOT_DIR/case"

cd "$CASE_DIR"

find . -maxdepth 1 -type d \
  \( -name '[1-9]*' -o -name 'processor*' -o -name 'postProcessing' \) \
  -exec rm -rf {} +

rm -rf constant/polyMesh
rm -f log.* *.foam
