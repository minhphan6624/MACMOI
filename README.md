# MAMCUI

MAMCUI is an Open-RMF deployment for collaborative mission control with physical TurtleBot3 robots. It combines robot-local bringup in `robot_ws`, RMF and `free_fleet` integration in `rmf_ws`, and the RMF web API/dashboard in `web`.

The repository is structured for a distributed lab setup:

- A central PC runs RMF common services, `free_fleet_adapter`, `zenohd`, the RMF web API server, and the web dashboard.
- One or more robot PCs run TurtleBot3 bringup, Nav2, and `zenoh-bridge-ros2dds`.

## Architecture

- `robot_ws`
  Robot-local TurtleBot3 bringup, hardware parameters, Nav2 launch files, and the lab Nav2 map.
- `rmf_ws`
  Adapter-side workspace containing `system_rmf_bringup`, `free_fleet_bringup`, and the local `free_fleet` source tree in `src/free_fleet`.
- `web`
  Source checkout of the RMF web API server and dashboard packages used for mission visualization and dispatch.
- `docs`
  Supporting runbooks, integration notes, troubleshooting logs, and controller experiments.

Main project interfaces:

- Single-robot fleet config: `rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_single_tb3_fleet.yaml`
- Two-robot fleet config: `rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml`
- RMF system package: `rmf_ws/src/system_rmf_bringup`
- Robot bringup entrypoint: `ros2 launch robot_bringup robot.launch.py ...`
- RMF system entrypoint: `ros2 launch system_rmf_bringup system.launch.py ...`
- Fleet adapter entrypoint: `ros2 launch free_fleet_bringup aiml_lab_ff_bringup.launch.xml ...`

## Repository Layout

```text
MACMOI/
├── robot_ws/   # Robot-side TurtleBot3 bringup and Nav2
├── rmf_ws/     # RMF assets, fleet configs, and free_fleet workspace
├── web/        # RMF web API server and dashboard
└── docs/       # Runbook, troubleshooting, and experiments
```

Older internal notes may refer to `adapter_ws`. In the current repository, the adapter-side workspace is `rmf_ws`, and all commands in this README use `rmf_ws/...`.

## Prerequisites

- System requirements
  - Ubuntu 24.04
  - ROS 2 Jazzy
  - Open-RMF installed or otherwise available on the central PC
  - `rmw_cyclonedds_cpp`
  - `zenohd`
  - `zenoh-bridge-ros2dds`
  - Python 3 with `venv`
  - Node.js 20+ and `pnpm`

In order to install these dependencies

- The central PC has `/opt/ros/jazzy` available.
- Each robot PC can build and source `robot_ws`.
- The robot-side Zenoh bridge configs live on the robot under `~/zenoh/config/`.

- Ros2 Jazzy is installed on both the robots' onboard SBCs and the central PC
- 

## Build And Install

### 1. Build `robot_ws`

Run on each robot PC if the workspace has not already been built:

```bash
cd /home/minhqphan/projects/MACMOI/robot_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select robot_bringup
```

### 2. Build `rmf_ws`

Run on the central PC:

```bash
cd /home/minhqphan/projects/MACMOI/rmf_ws
source /opt/ros/jazzy/setup.bash

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

rosdep install --from-paths src --ignore-src --rosdistro jazzy -yr
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
```

Notes:

- `rmf_ws/src/free_fleet` is part of this project workspace and may contain local integration changes.
- If you build with the venv activated, ROS build helper packages must also exist in that venv. The checked-in `requirements.txt` already includes `catkin-pkg`.

### 3. Install `web` Dependencies

Run on the central PC:

```bash
cd /home/minhqphan/projects/MACMOI/web
pnpm install
```

The web workspace uses the local Pipenv bootstrap under `web/pipenv-install` for Python dependencies used by the API server package.

## Environment Setup

### Central PC Shell

Use this for RMF common, the fleet adapter, and RMF task dispatch:

```bash
source /opt/ros/jazzy/setup.bash
cd /home/minhqphan/projects/MACMOI/rmf_ws
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export SYSTEM_RMF_SHARE=$(ros2 pkg prefix system_rmf_bringup)/share/system_rmf_bringup
export FREE_FLEET_BRINGUP_SHARE=$(ros2 pkg prefix free_fleet_bringup)/share/free_fleet_bringup
```

If you use a non-default ROS domain, export it in every central-PC shell that participates in RMF:

```bash
export ROS_DOMAIN_ID=<domain_id>
```

### Robot PC Shell

Use this on each robot PC:

```bash
source /opt/ros/jazzy/setup.bash
cd /home/minhqphan/projects/MACMOI/robot_ws
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
```

If the deployment uses a custom ROS domain, set the same `ROS_DOMAIN_ID` on each participating shell.

## Basic Run

### Single-Robot Physical Test

Current single-robot config:

```text
rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_single_tb3_fleet.yaml
```

Startup order:

1. Robot PC: launch TurtleBot3 hardware and Nav2.
2. Central PC: start `zenohd`.
3. Robot PC: start `zenoh-bridge-ros2dds`.
4. Central PC: launch the lab RMF system.
5. Central PC: dispatch a small RMF patrol.

Robot bringup:

```bash
ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

Zenoh router on the central PC:

```bash
zenohd
```

Zenoh bridge on the robot PC:

```bash
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
```

Lab RMF system on the central PC:

```bash
ros2 launch system_rmf_bringup system.launch.py \
  server_uri:=http://localhost:8000/_internal \
  use_sim_time:=false \
  headless:=false
```

### Two-Robot Physical Test

Current two-robot config:

```text
rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml
```

Startup order:

1. Robot 1 PC: launch TurtleBot3 hardware and Nav2.
2. Robot 2 PC: launch TurtleBot3 hardware and Nav2.
3. Central PC: start `zenohd`.
4. Robot 1 PC: start `zenoh-bridge-ros2dds`.
5. Robot 2 PC: start `zenoh-bridge-ros2dds`.
6. Central PC: launch the lab RMF system with the two-robot fleet config.
7. Central PC: dispatch RMF tasks after both robots appear in fleet state.

Robot bringup:

```bash
ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1
```

```bash
ros2 launch robot_bringup robot.launch.py robot_id:=tb3_2
```

Robot-side Zenoh bridges:

```bash
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
```

```bash
zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot2_zenoh.json5
```

Lab RMF system:

```bash
ros2 launch system_rmf_bringup system.launch.py \
  server_uri:=http://localhost:8000/_internal \
  config_file:=/home/minhqphan/projects/MACMOI/rmf_ws/src/free_fleet_bringup/config/fleet/aiml_lab_multi_tb3_fleet.yaml \
  use_sim_time:=false \
  headless:=false
```

### Web Interface

Start the API server on the central PC:

```bash
cd /home/minhqphan/projects/MACMOI/web/packages/api-server
pnpm start
```

Start the dashboard example in a second terminal:

```bash
cd /home/minhqphan/projects/MACMOI/web/packages/rmf-dashboard-framework
pnpm start:example examples/demo
```

Default local URLs:

- API server: `http://localhost:8000`
- Dashboard: `http://localhost:5173`

If you want RMF launches to publish to the web stack, pass the API server internal endpoint when supported:

```bash
server_uri:=http://localhost:8000/_internal
```

The checked-in `system.launch.py` already exposes a `server_uri` argument, for example:

```bash
ros2 launch system_rmf_bringup system.launch.py \
  server_uri:=http://localhost:8000/_internal \
  use_sim_time:=false \
  headless:=false
```

## Useful Commands

Dispatch a simple patrol task from the central PC:

```bash
ros2 run rmf_demos_tasks dispatch_patrol \
  -p source staging transfer destination \
  -n 1 \
  -st 0
```

Rebuild the RMF nav graph after editing the building file in `rmf_ws/src/system_rmf_bringup/maps/aiml-lab.building.yaml`:

```bash
source /opt/ros/jazzy/setup.bash

ros2 run rmf_building_map_tools building_map_generator nav \
  /home/minhqphan/projects/MACMOI/rmf_ws/src/system_rmf_bringup/maps/aiml-lab.building.yaml \
  /home/minhqphan/projects/MACMOI/rmf_ws/src/system_rmf_bringup/nav_graphs
```

If you need deeper operator notes or troubleshooting:

- [docs/project_runbook.md](docs/project_runbook.md)
- [docs/free_fleet_rmf_integration.md](docs/free_fleet_rmf_integration.md)
- [docs/free_fleet_rmf_troubleshooting.md](docs/free_fleet_rmf_troubleshooting.md)
- [docs/CONTROLLER_EXPERIMENTS.md](docs/CONTROLLER_EXPERIMENTS.md)

## Notes

- The single-robot config currently enables `tb3_1`.
- The two-robot config currently enables `tb3_1` and `tb3_2`.
- `robot_bringup` selects robot-specific Nav2 parameters from `robot_id`, defaulting to the checked-in TurtleBot3 parameter files.
- The README is intentionally concise; use the linked docs for extended runbooks, troubleshooting history, and experiment logs.
