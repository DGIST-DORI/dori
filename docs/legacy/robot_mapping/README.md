# Lidar-Only 2D SLAM

작성일: 2026-07-23

이 폴더는 Isaac Sim 전용 구성이 아니라, 실제 2D 라이다 센서를 가진 로봇에서 바로 옮겨서 쓸 수 있도록 만든 `lidar only` 2D SLAM 런타임이다.

핵심 조건:

- 입력 센서는 `sensor_msgs/msg/LaserScan` 하나만 사용
- IMU 없음
- wheel odometry 없음
- `cartographer_ros` 기반
- SLAMTEC RPLIDAR C1 자동 감지 및 드라이버 실행
- 이 폴더 자체는 별도 ROS package build 없이 실행 가능
- Jetson 에 폴더째 복사해서 `ros2 launch /abs/path/...` 형태로 실행 가능

## 왜 `slam_toolbox` 대신 `cartographer_ros` 인가

현재 워크스페이스의 `slam_toolbox` 구성은 `odom -> base_link` 입력을 전제로 잡고 있다. 반면 이번 목표는 오도메트리와 IMU 없이 라이다만으로 시작하는 것이다.

이 때문에 이번 폴더는 `cartographer_ros` 2D 모드를 쓴다.

- Cartographer ROS 공식 FAQ 에 따르면 2D 에서는 correlative scan matcher 를 local SLAM 에도 사용할 수 있어, odometry 나 IMU 없이도 동작시킬 수 있다.
- 반대로 기존 `ros2_2d_slam` 폴더의 `slam_toolbox` 구성은 `odom` TF 브리징을 포함하고 있어, 현재 구조 그대로는 pure lidar-only 시작점으로 맞지 않는다.

공식 참고:

- Cartographer ROS FAQ: https://google-cartographer-ros.readthedocs.io/en/latest/faq.html
- Cartographer ROS config reference: https://google-cartographer-ros.readthedocs.io/en/latest/configuration.html

## 필요한 입력

최소 요구 사항은 두 가지다.

1. `LaserScan` 토픽
2. 라이다 프레임과 로봇 본체 프레임 사이 TF

예:

- scan topic: `/scan`
- base frame: `base_link`
- laser frame: `laser`

만약 라이다 드라이버가 `base_link -> laser` TF 를 안 주면, 이 launch 가 정적 TF 를 대신 게시할 수 있다.

## 설치 패키지

Jetson 에서 최소한 아래 패키지는 있어야 한다.

```bash
sudo apt update
sudo apt install -y \
  ros-humble-cartographer-ros \
  ros-humble-nav2-map-server \
  ros-humble-rviz2
```

`sllidar_ros2`는 다음 순서로 자동 준비된다.

1. 이미 source 된 `sllidar_ros2` 패키지 재사용
2. 인접한 `../sllidar_ws/install/setup.bash` 재사용
3. 둘 다 없으면 공식 `Slamtec/sllidar_ros2` 저장소를 `.deps/sllidar_ws`에 clone하고 자동 빌드

따라서 최초 실행에는 네트워크와 `git`, `colcon`이 필요할 수 있다.

## C1 USB 권한 1회 설정

아래 명령을 한 번 실행하면 CP210x 장치에 `/dev/slamtec_c1` 별칭과 자동 접근 권한이 적용된다.

```bash
cd /home/data1/isaac_sim_ros/python_codes/lidar_only_slam
./scripts/install_udev_rule.sh
```

현재 PC에는 이 규칙을 적용해 두었다. 새 Jetson으로 폴더를 복사하면 그 장치에서도 위 명령을 한 번 실행한다.

## 빠른 시작

```bash
cd /home/data1/isaac_sim_ros/python_codes/lidar_only_slam
./scripts/run_mapping.sh rviz:=true
```

이 명령 하나가 다음을 자동 수행한다.

- `/dev/slamtec_c1`, CP210x `by-id`, `/dev/ttyUSB0` 순으로 C1 포트 감지
- 직렬 포트 권한 확인 및 필요 시 시스템 인증 요청
- `/scan` 메시지가 실제로 도착하면 기존 드라이버 재사용
- 발행자만 남고 데이터가 없으면 stale C1 프로세스를 정리
- 실제 `/scan` 데이터가 없으면 C1 드라이버를 `460800 baud`, `Standard` 모드로 시작
- USB 재연결로 드라이버가 종료되면 2초 후 자동 재시작
- 중복 실행은 runtime lock으로 차단
- `base_link -> laser` 정적 TF, Cartographer, occupancy grid와 RViz 실행

기본값:

- `scan_topic:=/scan`
- `start_lidar_driver:=auto` (`run_mapping.sh`가 `true` 또는 `false`로 결정)
- `serial_port:=auto`
- `serial_baudrate:=460800`
- `scan_mode:=Standard`
- `base_frame:=base_link`
- `laser_frame:=laser`
- `publish_laser_tf:=true`
- `laser_x:=0.0`
- `laser_y:=0.0`
- `laser_z:=0.0`
- `laser_roll:=0.0`
- `laser_pitch:=0.0`
- `laser_yaw:=0.0`
- `max_range:=16.0`
- `missing_data_ray_length:=16.5`

즉, 라이다가 base_link 와 사실상 같은 위치라고 보면 기본값 그대로 시작할 수 있다.

## 드라이버가 이미 TF 를 주는 경우

라이다 드라이버나 robot_state_publisher 가 이미 `base_link -> laser_frame` TF 를 게시하면, launch 내부 정적 TF 는 끄는 게 맞다.

예:

```bash
./scripts/run_mapping.sh \
  rviz:=true \
  publish_laser_tf:=false \
  scan_topic:=/scan \
  base_frame:=base_link \
  laser_frame:=base_scan
```

## 라이다가 base_link 와 정확히 일치하지 않는 경우

실제 장착 오프셋이 있으면 정적 TF 값을 넣어야 한다.

예:

```bash
./scripts/run_mapping.sh \
  rviz:=true \
  publish_laser_tf:=true \
  base_frame:=base_link \
  laser_frame:=laser \
  laser_x:=0.12 \
  laser_y:=0.0 \
  laser_z:=0.18 \
  laser_roll:=0.0 \
  laser_pitch:=0.0 \
  laser_yaw:=0.0
```

## Jetson 권장 실행 예시

Jetson 에서는 보통 GUI 없이 돌리고, RViz 는 별도 PC 에서 보는 편이 낫다.

Jetson:

```bash
cd /home/ubuntu/python_codes/lidar_only_slam
./scripts/install_udev_rule.sh
./scripts/run_mapping.sh \
  rviz:=false \
  scan_topic:=/scan \
  base_frame:=base_link \
  laser_frame:=laser
```

원격 PC:

```bash
source /opt/ros/humble/setup.bash
rviz2 -d /opt/ros/humble/share/cartographer_ros/configuration_files/demo_2d.rviz
```

주의:

- 원격 RViz 를 쓰려면 ROS 네트워크 환경이 서로 맞아야 한다.
- simplest path 는 Jetson 과 PC 가 같은 ROS_DOMAIN_ID / middleware 환경을 공유하는 것이다.

## 맵 저장

Cartographer 쪽 occupancy grid node 가 `/map` 을 내보내므로, 저장은 Nav2 map saver 로 하면 된다.

예:

```bash
cd /home/data1/isaac_sim_ros/python_codes/lidar_only_slam
./scripts/save_map.sh ./maps/lab_map
```

그러면 아래 파일이 생긴다.

- `maps/lab_map.pgm`
- `maps/lab_map.yaml`

## 주요 launch argument

- `scan_topic`
  - 기본값: `/scan`
- `start_lidar_driver`
  - 기본 동작: 스크립트가 `/scan` 발행자 유무에 따라 자동 결정
  - 강제 실행: `start_lidar_driver:=true`
  - 외부 드라이버 재사용: `start_lidar_driver:=false`
- `serial_port`
  - 기본 동작: C1 USB 포트 자동 감지
  - 직접 지정 예: `serial_port:=/dev/slamtec_c1`
- `serial_baudrate`
  - C1 기본값: `460800`
- `scan_mode`
  - C1 기본값: `Standard`
- `base_frame`
  - 기본값: `base_link`
- `laser_frame`
  - 기본값: `laser`
- `publish_laser_tf`
  - 기본값: `true`
- `laser_x`, `laser_y`, `laser_z`, `laser_roll`, `laser_pitch`, `laser_yaw`
  - 기본값: 모두 `0.0`
- `rviz`
  - 기본값: `false`
- `min_range`
  - 기본값: `0.10`
- `max_range`
  - C1 기본값: `16.0`
- `missing_data_ray_length`
  - C1 기본값: `16.5`
- `submap_range_data`
  - 기본값: `35`

예:

```bash
./scripts/run_mapping.sh \
  rviz:=true \
  scan_topic:=/scan \
  base_frame:=base_link \
  laser_frame:=laser \
  publish_laser_tf:=true \
  max_range:=16.0
```

## 입력 확인용 명령

```bash
source /opt/ros/humble/setup.bash
ros2 topic list
ros2 topic echo --once /scan
ros2 topic hz /scan
ros2 run tf2_ros tf2_echo base_link laser
```

## 기대 동작

정상 동작하면 다음이 보여야 한다.

- `/map` topic 이 생김
- Cartographer 가 `map`, `odom`, `base_link` 계층을 게시
- RViz 에서 LaserScan, trajectory, occupancy map 이 갱신됨

이 폴더 전용 RViz 설정은 `config/lidar_only_mapping.rviz`이며, 선택 설치되는
`cartographer_rviz` 플러그인 없이 기본 RViz 플러그인만 사용한다.

## 현재 실물 C1 검증 결과

2026-07-24 현재 연결된 RPLIDAR C1로 확인한 결과:

- USB: Silicon Labs CP2102N, `/dev/slamtec_c1 -> /dev/ttyUSB0`
- SLLIDAR health: OK
- firmware: 1.02
- scan mode: Standard
- `/scan`: 약 10 Hz
- C1 최대 거리: 16 m
- `/map`: 정상 발행, 해상도 0.05 m
- Cartographer trajectory 및 submap 생성 확인
- 전용 RViz에서 LaserScan, scan-matched points, TF, occupancy map 표시 확인

## 주의 사항

- 오도메트리와 IMU 없이 라이다만 쓰면, feature 가 적은 긴 복도나 대칭적인 공간에서는 드리프트가 커질 수 있다.
- 제자리 회전과 짧은 직진/회전을 섞어가며 천천히 맵핑하는 편이 안정적이다.
- 라이다 장착 오프셋이 틀리면 맵이 찢어지거나 벽이 두 겹으로 보인다.

## 다음 단계

이 폴더는 일단 mapping 전용 시작점이다.

다음에 확장하려면:

1. 저장한 `yaml/pgm` 맵을 Nav2 localization 에 연결
2. named goal CSV 체계를 붙이기
3. 채팅 출력 결과를 `/named_goal` 또는 Nav2 goal 로 자동 연결
