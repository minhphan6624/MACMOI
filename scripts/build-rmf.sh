#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"
rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release "$@"
source install/setup.bash

