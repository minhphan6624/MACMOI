# MACMOI

MACMOI is an Open-RMF deployment for collaborative mission control with
physical TurtleBot3 robots. It combines robot-local bringup, Open-RMF /
Free Fleet integration, a custom mission layer, and optional RMF web tooling.

The current mission is a two-robot package handoff:

```text
source -> transfer -> destination

tb3_1: source -> transfer
tb3_2: transfer -> destination
```

The mission layer owns package state, robot roles, transfer-zone rules, and the
operator-facing mission state. Open-RMF and Free Fleet handle traffic-aware
movement and Nav2 command dispatch.

## Repository Layout

```text
MACMOI/
├── robot_ws/   # Robot-side TurtleBot3 bringup, Nav2 config, and Nav2 map
├── rmf_ws/     # RMF assets, fleet configs, free_fleet, and mission_manager
├── web/        # RMF web API server and dashboard packages
└── docs/       # Runbooks, architecture notes, and troubleshooting notes
```

Main project interfaces:

- Robot bringup: `robot_ws/src/robot_bringup`
- Mission manager: `rmf_ws/src/mission_manager`
- RMF system bringup: `rmf_ws/src/system_rmf_bringup`
- Free Fleet bringup: `rmf_ws/src/free_fleet_bringup`
- Two-robot fleet config: `rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml`
- RMF building map: `rmf_ws/src/system_rmf_bringup/maps/aiml-lab.building.yaml`
- RMF nav graph: `rmf_ws/src/system_rmf_bringup/nav_graphs/1.yaml`

## Current Architecture

The deployment is distributed:

- Central PC: RMF core, `free_fleet_adapter`, mission manager, `zenohd`, and
  optional web/API services.
- Robot PCs: TurtleBot3 bringup, localization, Nav2, and
  `zenoh-bridge-ros2dds`.

The active RMF graph is intentionally constrained to the mission corridor:

```text
robot1_home <-> source
source <-> upstream_exit
upstream_exit <-> transfer      mutex: transfer_zone
transfer <-> downstream_exit    mutex: transfer_zone
downstream_exit <-> destination
destination <-> robot2_home
```

`upstream_exit` and `downstream_exit` are directional wait/clear points. The
shared `transfer` waypoint is the only managed mission resource.

Movement completion is reported through:

```text
mission_manager -> mission_execution_commands -> free_fleet Nav2 adapter
free_fleet Nav2 adapter -> mission_execution_results -> mission_manager
```

RMF task summaries are still used as a secondary completion path.

## Prerequisites

- Ubuntu 24.04
- ROS 2 Jazzy
- Open-RMF available on the central PC
- `rmw_cyclonedds_cpp`
- `zenohd`
- `zenoh-bridge-ros2dds`
- Python 3 with `venv`
- Node.js 20+ and `pnpm` for the optional web UI

Robot-side Zenoh bridge configs are expected to live on each robot, commonly
under `~/zenoh/config/`, and should expose namespaces matching the fleet robot
names: `tb3_1` and `tb3_2`.

## Build

Run commands from the repository root unless stated otherwise.

### Robot Workspace

Run on each robot PC:

```bash
cd robot_ws
source /opt/ros/jazzy/setup.bash
colcon build --symlink-install --packages-select robot_bringup
source install/setup.bash
```

### RMF Workspace

Run on the central PC:

```bash
cd rmf_ws
source /opt/ros/jazzy/setup.bash

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --symlink-install --cmake-args -DCMAKE_BUILD_TYPE=Release
source install/setup.bash
```

Notes:

- `rmf_ws/src/free_fleet` is part of this workspace and contains local
  integration changes.
- If you build with the virtual environment active, ROS build helper packages
  must exist in that environment. `rmf_ws/requirements.txt` includes
  `catkin-pkg`.

### Web Workspace

Only needed for the optional web/API workflow:

```bash
cd web
pnpm install
```

## Environment

### Central PC Shell

Use this in terminals that run RMF, Free Fleet, the mission manager, or RMF task
commands:

```bash
source /opt/ros/jazzy/setup.bash
cd rmf_ws
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export SYSTEM_RMF_SHARE=$(ros2 pkg prefix system_rmf_bringup)/share/system_rmf_bringup
export FREE_FLEET_BRINGUP_SHARE=$(ros2 pkg prefix free_fleet_bringup)/share/free_fleet_bringup
```

If you use a non-default ROS domain, set it in every participating shell:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

### Robot PC Shell

Use this on each robot PC:

```bash
source /opt/ros/jazzy/setup.bash
cd robot_ws
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

Use the same `ROS_DOMAIN_ID` as the central PC if one is configured.

## Run: Two-Robot Mission

### 1. Start Robots

On robot 1:

```bash
ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

On robot 2:

```bash
ros2 launch robot_bringup robot.launch.py robot_id:=tb3_2
```

Both robots should be localized before starting the fleet adapter.

### 2. Start Zenoh

On the central PC:

```bash
zenohd
```

On robot 1:

```bash
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
```

On robot 2:

```bash
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot2_zenoh.json5
```

### 3. Start RMF And Free Fleet

On the central PC:

```bash
cd rmf_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch system_rmf_bringup system.launch.py \
  use_sim_time:=false \
  headless:=false
```

The default launch uses the checked-in two-robot fleet config and RMF graph.

### 4. Start The Mission Manager

Start after both robots appear in `/fleet_states`:

```bash
cd rmf_ws
source /opt/ros/jazzy/setup.bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 run mission_manager mission_manager_node \
  --ros-args \
  -p mission_id:=m1 \
  -p total_packages:=3 \
  -p auto_start:=true
```

To start manually:

```bash
ros2 run mission_manager mission_manager_node \
  --ros-args \
  -p mission_id:=m1 \
  -p total_packages:=3 \
  -p auto_start:=false
```

Then publish:

```bash
ros2 topic pub --once /mission_commands std_msgs/msg/String \
  "{data: '{\"command\":\"start\",\"mission_id\":\"m1\"}'}"
```

## Monitor

Useful topics:

```bash
ros2 topic echo /fleet_states rmf_fleet_msgs/msg/FleetState
ros2 topic echo /mission_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local
ros2 topic echo /mission_execution_results std_msgs/msg/String
```

Expected movement completion logs:

```text
Published mission execution result: ...
Mission command completed from nav2_result: cmd_X
Mission command completed from task_summary: cmd_X
```

## Optional Web Interface

Start the API server:

```bash
cd web/packages/api-server
pnpm start
```

Start the dashboard example:

```bash
cd web/packages/rmf-dashboard-framework
pnpm start:example examples/demo
```

Default local URLs:

- API server: `http://localhost:8000`
- Dashboard: `http://localhost:5173`

To connect RMF to the API server, pass:

```bash
server_uri:=http://localhost:8000/_internal
```

to supported RMF/free_fleet launch files.

## Useful Checks

Dispatch a simple one-shot RMF movement task:

```bash
ros2 run rmf_demos_tasks dispatch_go_to_place \
  -F tb3_lab \
  -R tb3_1 \
  -p source \
  -st 0
```

Regenerate the RMF nav graph after editing the building map:

```bash
cd rmf_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash

ros2 run rmf_building_map_tools building_map_generator nav \
  src/system_rmf_bringup/maps/aiml-lab.building.yaml \
  src/system_rmf_bringup/nav_graphs
```

Then rebuild the affected bringup package:

```bash
colcon build --symlink-install --packages-select system_rmf_bringup
source install/setup.bash
```

## Documentation

Use these for details beyond the quick setup:

- [docs/project_runbook.md](docs/project_runbook.md)
- [docs/mission_layer_current_architecture.md](docs/mission_layer_current_architecture.md)
- [docs/mission_layer_current_stage_issues.md](docs/mission_layer_current_stage_issues.md)
- [docs/free_fleet_rmf_integration.md](docs/free_fleet_rmf_integration.md)
- [docs/free_fleet_rmf_troubleshooting.md](docs/free_fleet_rmf_troubleshooting.md)

## Notes

- The single-robot config enables `tb3_1`.
- The two-robot config enables `tb3_1` and `tb3_2`.
- `robot_bringup` selects robot-specific Nav2 parameters from `robot_id`.
- Robot-side `handling_simulator_node` instances simulate package load/unload
  and report completion on `mission_execution_results`.
