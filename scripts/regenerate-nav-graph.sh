#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"
rm -f src/macmoi_assets/nav_graphs/1.yaml

ros2 run rmf_building_map_tools building_map_generator nav \
  src/macmoi_assets/maps/aiml-lab.building.yaml \
  src/macmoi_assets/nav_graphs

colcon build --packages-select rmf_bringup macmoi_assets macmoi_free_fleet_bringup --symlink-install
source install/setup.bash

