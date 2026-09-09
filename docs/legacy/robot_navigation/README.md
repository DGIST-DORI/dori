Current ROS graph observed from Isaac Sim:

- `/scan` (`sensor_msgs/msg/LaserScan`), about 17 Hz, `frame_id=base_scan`
- `/odom` (`nav_msgs/msg/Odometry`), `header.frame_id=odom`, `child_frame_id=base_link`
- `/imu` (`sensor_msgs/msg/Imu`), `frame_id=sim_imu`
- `/cmd_vel` subscriber exists in Isaac Sim
- `/clock` is published, so `use_sim_time=true` is required

This folder adds the missing TF pieces needed for 2D SLAM:

- `base_link -> base_scan` as a static transform at `0 0 0`
- `odom -> base_link` by rebroadcasting the existing `/odom` topic into TF on the active sim clock
- `/odom -> /odom_restamped` by rewriting odometry timestamps onto the active sim clock
- `/scan -> /scan_restamped` by rewriting the scan timestamp onto the active sim clock
- `slam_toolbox` and `rviz` listen to isolated TF channels (`/tf_slam`, `/tf_static_slam`) so stale Isaac TF does not interfere
- `slam_toolbox` in async online mapping mode
- `map -> odom` is published by `slam_toolbox` after scans are processed; a short manual drive or rotation is enough to initialize it

Run:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_2d_slam.launch.py
```

Useful checks:

```bash
source /opt/ros/humble/setup.bash
ros2 topic echo --once /map
ros2 topic echo --once /tf
ros2 run tf2_tools view_frames
```

Open RViz together with SLAM:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_2d_slam.launch.py rviz:=true
```

Open RViz and the keyboard drive FPV window together for manual mapping:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_2d_slam.launch.py rviz:=true keyboard:=true
```

Keyboard drive notes:

- click the `FPV + Control Board` window first so it receives key input
- `W/S` changes linear speed, `A/D` changes angular speed
- `SPACE` stops immediately
- `Q` or `ESC` closes the FPV control window
- RViz is for map confirmation, the FPV window is for teleop input

Save the map after driving:

```bash
source /opt/ros/humble/setup.bash
ros2 run nav2_map_server map_saver_cli -f /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/isaac_map
```

Run Nav2 on the saved map:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_nav2.launch.py
```

Open RViz together with Nav2:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_nav2.launch.py rviz:=true
```

Nav2 notes:

- `isaac_nav2.launch.py` expects `/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/isaac_map.yaml`
- publish an initial pose in RViz (`2D Pose Estimate`) before sending a goal
- if localization drifts, tune `robot_radius` and the `base_link -> base_scan` static transform first

Named-point navigation can be layered on top of the saved map with a separate CSV file:

- occupancy map stays in `isaac_map.yaml` and `isaac_map.pgm`
- named goal points stay in `isaac_map.points.csv`
- each point is just `name,x,y,yaw_deg,frame_id`

Example file:

```csv
name,x,y,yaw_deg,frame_id
lab_door,1.25,-2.10,90.0,map
charging_station,0.30,0.80,0.0,map
```

Open the saved map, click a point, then enter its name and yaw in the right-side panel:

```bash
/usr/bin/python3 /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/scripts/named_points_editor.py --map_yaml /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/isaac_map.yaml --points_csv /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/isaac_map.points.csv
```

Run Nav2 with named-goal selection enabled:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_nav2.launch.py rviz:=true auto_initial_pose:=true named_nav:=true named_points_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/isaac_map.points.csv
```

Notes:

- `auto_initial_pose:=true` only seeds AMCL with a starting guess from the current odometry. It does not replace localization.
- If the robot did not start from roughly the same place where the map was created, leave `auto_initial_pose:=false` and use RViz `2D Pose Estimate` manually.
- The default Nav2 RViz config now shows the named goal marker, the global plan (`/plan`), and the local plan (`/local_plan`) so you can see both the selected destination and how Nav2 is steering around obstacles.

If you want a camera window together with Nav2, launch the FPV viewer:

```bash
source /opt/ros/humble/setup.bash
ros2 launch /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/launch/isaac_nav2.launch.py rviz:=true keyboard:=true auto_initial_pose:=true named_nav:=true named_points_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/isaac_map.points.csv
```

Nav2 viewer notes:

- in `isaac_nav2.launch.py`, `keyboard:=true` now opens a viewer-only FPV window
- it does not publish `/cmd_vel`, so it will not fight the Nav2 controller
- use RViz `2D Pose Estimate` if you need to set or correct the initial localization manually

Send a named destination:

```bash
source /opt/ros/humble/setup.bash
ros2 topic pub --once /named_goal std_msgs/msg/String "{data: lab_door}"
```

Useful named-goal commands:

- publish `reload` to `/named_goal` after editing the CSV file
- publish `list` to `/named_goal` to ask the bridge for the available keys
- watch `/named_goal_status` to see `sent`, `accepted`, `finished`, or `unknown`

This keeps the named-goal layer independent from SLAM, so you can remap or relocalize on the same occupancy map and still reuse the same destinations.
