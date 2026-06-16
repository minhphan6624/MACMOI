#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"
ros2 launch macmoi_free_fleet_bringup aiml_lab_ff_bringup.launch.xml "$@"

