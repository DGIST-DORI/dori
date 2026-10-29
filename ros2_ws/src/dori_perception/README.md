# dori_perception

## Depth camera topic policy

`dori_perception/dori_perception/depth_camera_node.py` uses **relative publish topic defaults**:

- `color/image_raw`
- `depth/image_raw`
- `depth/image_colormap`
- `color/camera_info`
- `depth/camera_info`

Production topic names are finalized in launch (`dori_bringup/launch/perception.launch.py`) via namespace/remapping, for example:

- `camera/color/image_raw`
- `camera/depth/image_raw`
- `camera/depth/image_colormap`
- `camera/color/camera_info`
- `camera/depth/camera_info`

Do not hardcode absolute `...` camera publish topics inside node code.
