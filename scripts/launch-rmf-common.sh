#!/usr/bin/env bash
set -e

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PROJECT_ROOT=$(cd -- "$SCRIPT_DIR/.." && pwd)

source "$SCRIPT_DIR/env-rmf.sh"

cd "$PROJECT_ROOT/rmf_ws"

has_config_file=false
has_initial_map=false

for arg in "$@"; do
  case "$arg" in
    config_file:=*) has_config_file=true ;;
    initial_map:=*) has_initial_map=true ;;
  esac
done

default_args=()
if [[ "$has_config_file" == false ]]; then
  default_args+=(config_file:=src/macmoi_assets/maps/aiml-lab.building.yaml)
fi
if [[ "$has_initial_map" == false ]]; then
  default_args+=(initial_map:=LG)
fi

ros2 launch rmf_bringup rmf_core.launch.xml "${default_args[@]}" "$@"
