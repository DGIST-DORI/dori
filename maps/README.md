# Real-robot maps

`live_navigation_20261023_1938.yaml` and its PGM are the saved map used by the
current robot. This map is site-specific; it is not a generic campus map.
Follow [AMM 50-10](../docs/user/DORI-AMM.md) for the separate hardware, LiDAR,
odometry and Cartographer launches. Save with `ros2 run nav2_map_server
map_saver_cli` using the documented timeout/durability settings. Select the new
YAML via `ros2 launch dori_bringup real_robot.launch.py map:=/absolute/site.yaml`.

`web_goals.example.json` contains the saved destinations for this exact map.
To use them as the initial local destination store, before starting the web UI:

```bash
cp -n maps/web_goals.example.json maps/web_goals.json
```

The writable `web_goals.json` and backup are ignored by Git. Destinations are
keyed by map contents, dimensions, resolution and origin; a different map needs
its own destinations.
