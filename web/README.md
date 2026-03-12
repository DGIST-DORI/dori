# DORI Dashboard Frontend (`web`)

This directory contains the Vite/React frontend for the DORI dashboard.

## Build (Required before ROS launch)

Build frontend assets before launching `dashboard_pkg` from the ROS workspace root.

```bash
cd web
npm ci   # or: npm install
npm run build
```

After the build completes, continue from the ROS workspace root:

```bash
cd ..
colcon build --symlink-install
source install/setup.bash
ros2 launch dashboard_pkg dashboard.launch.py
```

## Access

- Dashboard: `http://[Robot IP]:3000`
- ROS WebSocket bridge: `ws://[Robot IP]:9090`

Examples:

```text
# Same machine (robot/local)
http://localhost:3000
ws://localhost:9090

# Another device on same network (remote)
http://[Robot IP]:3000
ws://[Robot IP]:9090
```

For broader project context, see the root README: `../README.md`.
