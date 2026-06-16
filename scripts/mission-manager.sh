#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

MISSION_ID=${1:-m1}
TOTAL_PACKAGES=${2:-3}
AUTO_START=${3:-true}

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"
ros2 run mission_manager mission_manager_node \
  --ros-args \
  -p mission_id:="$MISSION_ID" \
  -p total_packages:="$TOTAL_PACKAGES" \
  -p auto_start:="$AUTO_START"

