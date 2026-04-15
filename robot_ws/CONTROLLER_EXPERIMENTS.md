# Nav2 Controller Experiments in `robot_ws`

This workspace supports swapping Nav2 controller plugins by changing the Nav2 parameter file passed into the launch files. The per-robot defaults now point at robot-specific RPP configs.

## Current setup

- Main robot launch: `src/robot_bringup/launch/robot.launch.py`
- Nav2-only launch: `src/robot_bringup/launch/nav2.launch.py`
- Per-robot Nav2 params:
  - `src/robot_bringup/config/nav2_waffle_pi_tb3_1.yaml`
  - `src/robot_bringup/config/nav2_waffle_pi_tb3_2.yaml`
- Standalone experiment config: `src/robot_bringup/config/nav2_waffle_pi_rpp.yaml`

The active controller is configured under:

- `controller_server.ros__parameters.controller_plugins`
- `controller_server.ros__parameters.FollowPath`

The per-robot configs now use:

```yaml
FollowPath:
  plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
```

## Controller plugins available on this machine

These packages are installed in the current ROS 2 Jazzy environment:

- `dwb_core`
- `nav2_regulated_pure_pursuit_controller`
- `nav2_mppi_controller`
- `nav2_rotation_shim_controller`
- `nav2_graceful_controller`

That means you can experiment with at least these plugin types:

- `dwb_core::DWBLocalPlanner`
- `nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController`
- `nav2_mppi_controller::MPPIController`
- `nav2_rotation_shim_controller::RotationShimController`
- `nav2_graceful_controller::GracefulController`

## Fastest workflow

1. Launch the robot with `robot_id:=tb3_1` or `robot_id:=tb3_2` to use the matching per-robot RPP config.
2. Override `params_file:=...` only when you want to test a different controller file.
3. Drive a few repeatable navigation trials and compare behavior.

Example:

```bash
cd /home/minhqphan/projects/MAMCUI/robot_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch robot_bringup robot.launch.py \
  robot_id:=tb3_1
```

For the second robot:

```bash
cd /home/minhqphan/projects/MAMCUI/robot_ws
source /opt/ros/jazzy/setup.bash
source install/setup.bash
ros2 launch robot_bringup robot.launch.py \
  robot_id:=tb3_2
```

You can still override the file directly:

```bash
ros2 launch robot_bringup robot.launch.py \
  robot_id:=tb3_1 \
  params_file:=/home/minhqphan/projects/MAMCUI/robot_ws/src/robot_bringup/config/nav2_waffle_pi_rpp.yaml
```

You can do the same with `nav2.launch.py` if hardware is already running separately.

## Recommended experiments

### 1. Baseline: per-robot RPP

The default `tb3_1` and `tb3_2` configs now use regulated pure pursuit as the main controller.

### 2. Regulated Pure Pursuit

Good first alternative for TurtleBot3 hardware. It is simpler than DWB and often easier to tune on real robots.

Replace the `FollowPath` block with something like:

```yaml
FollowPath:
  plugin: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
  desired_linear_vel: 0.25
  lookahead_dist: 0.5
  min_lookahead_dist: 0.3
  max_lookahead_dist: 0.9
  lookahead_time: 1.5
  rotate_to_heading_angular_vel: 1.0
  transform_tolerance: 0.1
  use_velocity_scaled_lookahead_dist: true
  min_approach_linear_velocity: 0.05
  approach_velocity_scaling_dist: 0.6
  use_collision_detection: true
  max_allowed_time_to_collision_up_to_lookahead_dist: 1.0
  use_regulated_linear_velocity_scaling: true
  use_cost_regulated_linear_velocity_scaling: true
  cost_scaling_dist: 0.3
  cost_scaling_factor: 10.0
  regulated_linear_scaling_min_radius: 0.9
  regulated_linear_scaling_min_speed: 0.1
  use_rotate_to_heading: true
  allow_reversing: false
  rotate_to_heading_min_angle: 0.785
  max_angular_accel: 3.2
```

This is close to the commented block already present in your default YAML.

### 3. MPPI

Useful if you want more aggressive, smoother optimization-based control, but it is heavier and has more tuning surface area.

Start from the Jazzy Nav2 defaults in `/opt/ros/jazzy/share/nav2_bringup/params/nav2_params.yaml` and adjust for your robot:

```yaml
FollowPath:
  plugin: "nav2_mppi_controller::MPPIController"
  motion_model: "DiffDrive"
  time_steps: 56
  model_dt: 0.05
  batch_size: 1000
  iteration_count: 1
  prune_distance: 1.7
  transform_tolerance: 0.1
  temperature: 0.3
  gamma: 0.015
  visualize: false
  regenerate_noises: true
  vx_max: 0.3
  vx_min: 0.0
  vy_max: 0.0
  wz_max: 1.0
  ax_max: 3.0
  ax_min: -2.5
  az_max: 3.2
  vx_std: 0.2
  vy_std: 0.0
  wz_std: 0.4
  critics: [
    "ConstraintCritic", "CostCritic", "GoalCritic",
    "GoalAngleCritic", "PathAlignCritic", "PathFollowCritic",
    "PathAngleCritic", "PreferForwardCritic"]
```

For TurtleBot3, keep `motion_model: "DiffDrive"` and `vy_max: 0.0`.

### 4. Rotation shim over another controller

This is useful when the robot struggles to align cleanly before following the path.

Conceptually:

```yaml
FollowPath:
  plugin: "nav2_rotation_shim_controller::RotationShimController"
  primary_controller: "nav2_regulated_pure_pursuit_controller::RegulatedPurePursuitController"
  angular_dist_threshold: 0.785
  forward_sampling_distance: 0.5
  rotate_to_heading_angular_vel: 1.0
  max_angular_accel: 3.2
```

This is usually worth trying with regulated pure pursuit on a differential robot.

## What to measure

Use the same start-goal pairs for every controller and compare:

- Does it oscillate in narrow spaces?
- Does it overshoot at the goal?
- Does it rotate too much before moving?
- Does it clip corners near obstacles?
- Does it recover well when the path changes?
- Is CPU usage acceptable on the robot computer?

Useful topics and checks:

```bash
ros2 topic echo /cmd_vel
ros2 topic hz /cmd_vel
ros2 param get /controller_server controller_plugins
ros2 lifecycle get /controller_server
```

If enabled, compare local plan and costmap behavior in RViz as well.

## Practical advice for TurtleBot3

- Try `RegulatedPurePursuitController` first.
- Use `RotationShimController` if heading alignment is a weak point.
- Keep `DWBLocalPlanner` as the baseline for comparison.
- Try `MPPIController` only after you have a solid baseline, because it takes more tuning effort.

## Important note about builds

If you pass a config file by absolute source path, you do not need to rebuild just to test it.

If you want the new YAML to be installed into the package share directory and used like a packaged asset, rebuild:

```bash
cd /home/minhqphan/projects/MAMCUI/robot_ws
source /opt/ros/jazzy/setup.bash
colcon build --packages-select robot_bringup
source install/setup.bash
```
