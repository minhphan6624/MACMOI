#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"
ros2 launch rmf_bringup system.launch.py "$@"

