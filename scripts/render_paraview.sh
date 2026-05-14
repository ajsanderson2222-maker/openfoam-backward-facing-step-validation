#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Debian/Ubuntu ParaView packages install paraview.simple here, but pvpython
# may not include the system dist-packages path when launched from some shells.
export PYTHONPATH="/usr/lib/python3/dist-packages${PYTHONPATH:+:$PYTHONPATH}"

pvpython -c "import paraview.simple" >/dev/null

if pvpython --force-offscreen-rendering --version >/dev/null 2>&1; then
    pvpython --force-offscreen-rendering scripts/render_paraview.py "$@"
else
    pvpython scripts/render_paraview.py "$@"
fi
