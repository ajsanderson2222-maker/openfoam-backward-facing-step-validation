#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASE_DIR="$ROOT_DIR/case"

cd "$CASE_DIR"

export WM_PROJECT_DIR="${WM_PROJECT_DIR:-/usr/share/openfoam}"

blockMesh | tee log.blockMesh
checkMesh | tee log.checkMesh
simpleFoam | tee log.simpleFoam

touch backward-facing-step.foam
