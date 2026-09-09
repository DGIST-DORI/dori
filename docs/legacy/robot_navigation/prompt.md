# Prompt Profiles

현재 프롬프트는 상황별로 분리해서 쓰는 구조가 맞다.

- `prompt.txt`
  현재 기본 프롬프트다.
  `test_loop` 맵과 `test_loop.points.csv` 기준의 목적지 선택에 맞춰져 있다.

- `prompt_dgist.txt`
  DGIST 캠퍼스 안내용 프롬프트다.
  건물, 시설, 교수님 이름 등 학교 컨텍스트가 들어 있다.

사용 방법:

- `test_loop` 용
  `-p prompt_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/prompt.txt`

- DGIST 용
  `-p prompt_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/prompt_dgist.txt`

예시:

```bash
/usr/bin/python3 /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/scripts/text_llm_named_goal.py \
  --ros-args \
  -p points_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/maps/test_loop.points.csv \
  -p prompt_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/prompt.txt
```

```bash
/usr/bin/python3 /home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/scripts/text_llm_named_goal.py \
  --ros-args \
  -p points_file:=/path/to/dgist.points.csv \
  -p prompt_file:=/home/data1/isaac_sim_ros/python_codes/ros2_2d_slam/prompt_dgist.txt
```
