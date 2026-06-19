# Step 1 - Start zenohd

## Start zenohd

```bash
cd ~/zenoh/
./zenohd
```

# Step 2 - Robot 

ssh ubuntu@192.168.50.101
ssh ubuntu@192.168.50.102

## Start zenoh brdige on robots

**Namespaced bridges**
robot1:

```bash 
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
~/zenoh/bin/zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot1_zenoh.json5
```

robot2:
```bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
~/zenoh/bin/zenoh-bridge-ros2dds -c ~/zenoh/config/tb3_robot2_zenoh.json5
```

**Non-namespace bridges**
```bash 
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
~/zenoh/bin/zenoh-bridge-ros2dds -c ~/zenoh/config/robot_mission_topics_zenoh.json5
```



## Bringup robot

Robot1

```bash
cd MACMOI
source robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_1 enable_handling_node:=false
```

Robot2

```bash
cd MACMOI
source robot_ws/install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch robot_bringup robot.launch.py robot_id:=tb3_2 enable_handling_node:=false
```
# Step 3 - API Server + Web things

Api Server

```bash
source install/setup.bash

cd web/packages/api-server
pnpm start
```

Web Interface:
```bash 
cd web/packages/rmf-dashboard-framework
pnpm start:example examples/demo
```

# Step 4 - Start rmf+ free fleet

Both

```bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch rmf_bringup system.launch.py server_uri:=http://localhost:8000/_internal
```

Separate:

RMF:

```bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch rmf_bringup rmf_core.launch.py server_uri:=http://localhost:8000/_internal
```

Free-Fleet
```bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 launch macmoi_free_fleet_bringup aiml_lab_ff_bringup.launch.xml server_uri:=http://localhost:8000/_internal
```

# Step 5 - Run handling node (on central PC)

Make sure to match the misison id with what's running

Handler for robot 1
```bash
source robot_ws/install/setup.bash

ros2 run robot_bringup handling_simulator_node --ros-args \
  -p robot_id:=tb3_1 \
  -p mission_id:=m1 \
  -p handling_duration_sec:=5.0
```

Handler for robto 2
```bash
source robot_ws/install/setup.bash

ros2 run robot_bringup handling_simulator_node --ros-args \
  -p robot_id:=tb3_2 \
  -p mission_id:=m1 \
  -p handling_duration_sec:=5.0
```


# Inspection topic commands

/mission_events: 
```bash
ros2 topic echo --full-length /mission_events std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data
```

/mission_commands:
```bash
ros2 topic echo --full-length /mission_commands std_msgs/msg/String --field data
```

Misison execution related:

```bash
ros2 topic echo /mission_execution_commands std_msgs/msg/String
ros2 topic echo /mission_execution_results std_msgs/msg/String
```

/mission_state related

```bash
ros2 topic echo --full-length /mission_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data

ros2 topic echo --full-length /mission_debug_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data
```

# Step 6 - RUn MIssion node

```bash
source .venv/bin/activate
source install/setup.bash
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp

ros2 run mission_manager mission_manager_node \
  --ros-args \
  -p mission_id:=m1 \
  -p total_packages:=3 \
  -p auto_start:=true
```

# Inspection topic commands

/mission_events: 
```bash
ros2 topic echo --full-length /mission_events std_msgs/msg/String \
  --qos-reliability reliable \
  --qos-durability transient_local \
  --field data
```

/mission_commands:
```bash
ros2 topic echo --full-length /mission_commands std_msgs/msg/String --field data
```

Misison execution related:

```bash
ros2 topic echo /mission_execution_commands std_msgs/msg/String
ros2 topic echo /mission_execution_results std_msgs/msg/String
```

/mission_state related

```bash
ros2 topic echo --full-length /mission_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data

ros2 topic echo --full-length /mission_debug_state std_msgs/msg/String --qos-reliability reliable --qos-durability transient_local --field data
```

# Operator Command

Pause

```bash 
ros2 topic pub --once /mission_commands std_msgs/msg/String \
"{data: '{\"mission_id\":\"m1\",\"command\":\"pause\"}'}"
```

Resume 

```bash 
ros2 topic pub --once /mission_commands std_msgs/msg/String \
"{data: '{\"mission_id\":\"m1\",\"command\":\"resume\"}'}"
```

Abort

```bash 
ros2 topic pub --once /mission_commands std_msgs/msg/String \
"{data: '{\"mission_id\":\"m1\",\"command\":\"abort\"}'}"
```
# Notes:
- Restart handling node when running new mission
