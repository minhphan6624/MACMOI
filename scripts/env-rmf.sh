#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)
RMF_WS="$PROJECT_ROOT/rmf_ws"

source /opt/ros/jazzy/setup.bash
source "$RMF_WS/.venv/bin/activate"

if [[ -f "$RMF_WS/install/setup.bash" ]]; then
  source "$RMF_WS/install/setup.bash"
fi

export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

