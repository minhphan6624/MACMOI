# Free Fleet / RMF Troubleshooting Log

This document tracks issues found while integrating the physical TurtleBot3
robot with Open-RMF through `free_fleet`.

For setup context, see `docs/free_fleet_rmf_integration.md`.

# 1. Current Issues

# `free_fleet_adapter` exits with code `-11`

Status: resolved by downgrading `numpy` to `1.26.0`.

Symptom: `[ERROR] [fleet_adapter.py-*]: process has died [..., exit code -11, cmd '.../fleet_adapter.py ...']`

Observed in:

- the lab adapter launch using `tb3_lab_fleet.yaml` and the generated lab nav graph
- the stock `free_fleet` Nav2 TurtleBot3 example, once it can discover the RMF schedule node

Current conclusion:

This is probably not caused by the lab building map, physical robot, robot-side Zenoh bridge, lab fleet config, or lab coordinate alignment. The stock `free_fleet` example also crashes in a similar startup phase.

The suspected crash point is native RMF / adapter startup around fleet registration. In the logs, the adapter computes the coordinate transform and then dies before robot initialization logs appear.

Further inspection:

The adapter adapter is not exiting because of a normal Python error. exit code -11 is a segmentation fault, so something in the native C++ layer underneath the Python adapter is crashing.
In a recent Open-RMF Jazzy bug report, the crash happens in the same place, right after the log line `Transformation error estimate for ...` and when the adapter constructs the RMF Transformation object. That issue was reported on Ubuntu 24.04, Jazzy, with RMF installed from binaries, which matches our setup

So the likely problem is: There is a bug in the Jazzy binary stack around fleet adapter transform setup, not necessarily a mistake in the map or robot integration. Your logs match that failure pattern very closely: RMF schedule discovery works, query registration works, mirror sync works, transform estimation is printed, then the process segfaults immediately.

What that means in practical terms:

The adapter is getting far enough to join RMF traffic scheduling successfully.
It is also getting far enough to read your config and compute the transform estimate.
The crash is likely happening when the Python adapter crosses into the compiled rmf_adapter native code to create or use the transformation object.

If this failure returns: Run the stock example adapter or lab adapter under gdb.
After the crash, run `bt` and inspect / save the backtrace.

Resolution: downgrade `numpy` in the adapter environment to `1.26.0`.

# 2. Resolved / Investigated Issues

### TurtleBot3 battery percentage is outside RMF's expected SOC range

Status: locally patched in the `free_fleet_adapter` source clone.

Symptom:

The adapter receives a `sensor_msgs/msg/BatteryState.percentage` value like
`31.1`, then RMF rejects it because robot battery state-of-charge must be in
the `0.0..1.0` range.

Cause:

The apt-installed TurtleBot3 node may publish a 0-to-100 percentage. ROS 2 and
RMF expect battery state-of-charge to be a fraction: `31.1%` should be `0.311`.

Local adapter-side compatibility patch:

```python
percentage = battery_state.percentage
if percentage > 1.0 and percentage <= 100.0:
    percentage /= 100.0
self.battery_soc = percentage
```

Preferred long-term cleanup:

Publish a normalized `BatteryState` on the robot side, or add a small
republisher/normalizer node so the upstream `free_fleet` code can stay
unchanged.

### Adapter registers the robot successfully

Status: current healthy startup target.

Expected adapter log shape:

```text
Successfully added robot [<robot_name>] to the fleet [tb3_lab]
Charger waypoint for robot [tb3_lab/<robot_name>] set to index [0]
```

Meaning:

The adapter has read the fleet config and nav graph, connected to RMF schedule,
initialized the robot pose, created an RMF robot update handle, and registered
the robot with the `tb3_lab` fleet.

This is a startup/registration milestone. Still perform a direct Nav2 test, a
Zenoh Nav2 goal test, `/fleet_states` inspection, and a single-waypoint RMF
patrol before running longer patrols.

### Missing Python `catkin_pkg` while building `free_fleet`

Status: resolved.

Symptom:

```text
ModuleNotFoundError: No module named 'catkin_pkg'
```

Context:

`colcon build` was being run with the adapter workspace venv activated, so ROS
build scripts were executed with the venv's Python interpreter.

Fix:

Install ROS build-helper Python packages into the same venv, including
`catkin_pkg`.

Notes:

If building ROS packages inside an activated venv, the venv needs the Python
modules required by `ament` / ROS build tooling.

### Adapter could not initialize because RMF schedule node was missing

Status: resolved for the lab RMF common launch.

Symptom:

```text
AssertionError: Unable to initialize fleet adapter. Please ensure RMF Schedule Node is running
```

Cause:

`free_fleet_adapter` was launched before RMF common / core services were
running.

Fix:

Launch the RMF common services first, then launch the adapter in a second shell
with the same ROS environment and ROS domain.

Important check:

If this error appears again, verify that the RMF common terminal is still
running and that both terminals have the same `ROS_DOMAIN_ID`.

### RMF building map server could not find the lab building file

Status: resolved.

Symptom:

```text
building_map_server ... FileNotFoundError: [Errno 2] No such file or directory
```

Cause:

The launch command referenced an old building filename.

Current building file:

```text
/home/minhqphan/projects/MAMCUI/adapter_ws/src/rmf_asset/maps/aiml-lab.building.yaml
```

Result after fix:

`building_map_server` successfully opens the lab PNG and reports that it is
ready to serve the map.

### `reference_coordinates` used raw building / image coordinates

Status: resolved.

Symptom:

The adapter reported a high transform error estimate:

```text
Transformation error estimate for LG: 2.63...
```

Cause:

The fleet config's `reference_coordinates.rmf` used the raw coordinates from
the `.building.yaml` file. `free_fleet_adapter` needs the RMF-world coordinates
from the generated nav graph.

Fix:

Update `reference_coordinates.rmf` in the fleet config to use waypoint
coordinates from:

```text
/home/minhqphan/projects/MAMCUI/adapter_ws/src/rmf_asset/generated_nav_graphs/1.yaml
```

Result after fix:

The transform error estimate dropped to roughly `1e-09` in the lab adapter
launch.

### Temporary charger was referenced but not marked in the building map

Status: corrected; did not resolve the adapter segfault.

Symptom / concern:

The fleet config referenced:

```text
charger: "robot1_home"
```

but `robot1_home` was not marked as a charger in the building file.

Fix:

Mark `robot1_home` as a charger in the lab `.building.yaml`:

```yaml
{is_charger: [4, true]}
```

Then regenerate the nav graph.

Result:

This made the lab site semantics more consistent, but the adapter still exits
with code `-11`.

### RMF dispatcher reports no bids for dispatched tasks

Status: understood; not the current blocker.

Symptom:

```text
Task action for [...] did not receive any bids
Dispatcher Bidding Result: task [...] has no submissions during bidding
```

Meaning:

RMF task dispatcher is running, but no active fleet adapter submitted a bid for
the task.

Likely causes:

- adapter is not running
- adapter crashed
- adapter did not initialize a robot
- task is unsupported by the fleet
- robot is unavailable / not registered with the fleet

In the stock example attempt, tasks were dispatched while no healthy example
fleet adapter / robot was available to bid.

### RMF common terminal prints schedule update timeout messages

Status: observed; not proven fatal.

Symptom:

```text
Requesting new schedule update because update timed out
```

Current interpretation:

This can be noisy while visualizer / mirror nodes request schedule updates. It
was not the primary cause of the adapter crash. The building map server and RMF
common services should still be checked for crashes separately.

### `building_map_server` reports unable to generate GeoJSON

Status: observed; not treated as blocker for smoke testing.

Symptom:

```text
unable to generate GeoJSON for this map.
```

Current interpretation:

The map server can still open the lab PNG and serve the building map. This was
not treated as the adapter crash cause.

### RViz reports stereo is not supported

Status: harmless.

Symptom:

```text
[rviz2]: Stereo is NOT SUPPORTED
```

Current interpretation:

This is an RViz / graphics capability warning and is not related to the
`free_fleet_adapter` crash.

### Zenoh router prints query timeout / "Query not found" warnings

Status: investigate if paired with navigation failure.

Observed warning shape:

```text
Didn't receive final reply for query ... Timeout(10s)!
Route reply: Query not found!
Route final reply: Query not found!
```

Meaning:

A Zenoh query did not get a final reply before the timeout or a late reply could
not be routed back to the original requester.

For this Nav2 free-fleet setup, important queried action endpoints include:

```text
<robot_name>/navigate_to_pose/_action/send_goal
<robot_name>/navigate_to_pose/_action/get_result
<robot_name>/navigate_to_pose/_action/cancel_goal
```

If the warnings happen during startup but the adapter later prints
`Navigation goal [...] accepted` and the robot moves, treat them as background
noise for that test.

If the warnings appear each time a task is dispatched and the adapter does not
print goal-accepted / goal-reached logs, check that the robot-side Nav2 action
exists and that the robot-side Zenoh bridge config exposes the
`navigate_to_pose` action for the same namespace as the fleet config robot key.

### RMF patrol motion looks wrong while direct Nav2 goals look correct

Status: coordinate/localization issue to debug methodically.

Important distinction:

Nav2 AMCL initial pose should be the physical robot's real pose in the Nav2
map, not automatically the RMF charger waypoint `robot1_home`.

`robot1_home` is the RMF charger waypoint for `tb3_1`. It corresponds to about
`[0.5564, 2.0371]` in the Nav2 map frame.

Debug path:

1. Set AMCL/RViz initial pose to the robot's real physical location.
2. Send direct Nav2 goals at the known waypoint map-frame coordinates.
3. Dispatch `ros2 run rmf_demos_tasks dispatch_patrol -p robot1_home -n 1 -st 0`.
4. Compare the adapter's `Commanding [...] to navigate to [...]` output against
   the expected Nav2 coordinates.
5. Only try a 4-point patrol after one waypoint behaves correctly.

# Debugging Notes

Useful question for each failure: Does the stock free_fleet example fail the same way?

If yes, debug environment / runtime compatibility before editing the lab map.

If no, compare the lab fleet config, generated nav graph, charger waypoints, level names, robot names, and reference coordinates against the stock example.
