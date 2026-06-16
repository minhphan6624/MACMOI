#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

TOPIC=${1:-/mission_state}

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"
ros2 topic echo --full-length "$TOPIC" std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data

