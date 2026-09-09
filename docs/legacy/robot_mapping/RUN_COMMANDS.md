# 실행 명령 모음

대상 폴더:

```bash
cd /home/data1/isaac_sim_ros/python_codes/lidar_only_slam
```

## 1. 새 PC 또는 Jetson에서 최초 1회

필수 ROS 패키지를 설치한다.

```bash
sudo apt update
sudo apt install -y \
  ros-humble-cartographer-ros \
  ros-humble-nav2-map-server \
  ros-humble-rviz2 \
  python3-colcon-common-extensions \
  git
```

SLAMTEC C1 USB 권한과 `/dev/slamtec_c1` 별칭을 설치한다.

```bash
./scripts/install_udev_rule.sh
```

설치 후 USB를 다시 연결하고 다음을 확인한다.

```bash
ls -l /dev/slamtec_c1
```

## 2. 데스크톱에서 매핑과 RViz 실행

```bash
./scripts/run_mapping.sh rviz:=true
```

이 명령은 다음 작업을 자동 수행한다.

- SLAMTEC C1 직렬 포트 감지
- 실제 `/scan` 데이터 수신 여부 확인
- 기존의 정상 LaserScan 드라이버가 있으면 재사용
- 데이터가 없는 stale SLLIDAR 프로세스 정리
- 필요한 경우 공식 `sllidar_ros2` clone 및 build
- C1 드라이버, 정적 TF, Cartographer, occupancy grid와 RViz 실행

## 3. Jetson headless 실행

```bash
./scripts/run_mapping.sh \
  rviz:=false \
  scan_topic:=/scan \
  base_frame:=base_link \
  laser_frame:=laser
```

## 4. 실제 장착 위치 반영

아래 값은 예시이므로 실제 장착 치수로 바꾼다.

```bash
./scripts/run_mapping.sh \
  rviz:=true \
  publish_laser_tf:=true \
  laser_x:=0.12 \
  laser_y:=0.0 \
  laser_z:=0.18 \
  laser_roll:=0.0 \
  laser_pitch:=0.0 \
  laser_yaw:=0.0
```

로봇이 이미 `base_link -> laser` TF를 게시한다면 다음처럼 내부 TF를 끈다.

```bash
./scripts/run_mapping.sh \
  rviz:=true \
  publish_laser_tf:=false \
  laser_frame:=laser
```

## 5. 상태 확인

```bash
source /opt/ros/humble/setup.bash
ros2 node list
ros2 topic info /scan
ros2 topic hz /scan
ros2 topic info /map
ros2 run tf2_ros tf2_echo map base_link
```

정상 기준:

- `/sllidar_node` 존재
- `/cartographer_node` 존재
- `/scan` 발행자 1개, 약 10 Hz
- `/map` 발행자 1개

## 6. 맵 저장

```bash
./scripts/save_map.sh ./maps/lab_map
```

생성 파일:

```text
maps/lab_map.pgm
maps/lab_map.yaml
```

## 7. 종료와 재시작

실행한 터미널에서 `Ctrl+C`로 종료한다.

```bash
./scripts/run_mapping.sh rviz:=true
```

이미 실행 중일 때 다시 실행하면 중복 SLAM을 막기 위해 다음 메시지와 함께 종료된다.

```text
Lidar-only mapping is already running.
Stop the existing run with Ctrl+C before starting another one.
```

## 8. 주요 강제 옵션

외부 `/scan` 드라이버를 반드시 재사용:

```bash
./scripts/run_mapping.sh rviz:=true start_lidar_driver:=false
```

C1 드라이버를 반드시 실행:

```bash
./scripts/run_mapping.sh \
  rviz:=true \
  start_lidar_driver:=true \
  serial_port:=/dev/slamtec_c1
```

