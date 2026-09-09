# 작업 세션 정리

작업일: 2026-07-24  
대상 센서: SLAMTEC RPLIDAR C1  
ROS 배포판: ROS 2 Humble

## 요청과 진행 경과

### 1. 실제 LiDAR 장치 확인

처음에는 Isaac Sim의 `/scan`을 확인하는 작업으로 이해했으나, 사용자가 실제
SLAMTEC LiDAR라고 정정했다.

USB 진단 결과:

- USB 변환기: Silicon Labs CP2102N
- USB ID: `10c4:ea60`
- 최초 장치 경로: `/dev/ttyUSB0`
- 당시 사용자 계정에는 `dialout` 권한이 없었음

### 2. C1 모델에 맞는 공식 드라이버 적용

일반 `rplidar_ros`의 115200/256000 baud 시도는 timeout이 발생했다.
사용자가 모델이 C1이며 공식 저장소가 `Slamtec/sllidar_ros2`라고 알려주었다.

공식 드라이버를 다음 워크스페이스에 clone하고 build했다.

```text
/home/data1/isaac_sim_ros/python_codes/sllidar_ws
```

C1 공식 설정:

- serial baudrate: `460800`
- scan mode: `Standard`
- topic: `/scan`
- frame: `laser`

실물 장치 확인 결과:

- SLLIDAR serial number: `6509E18AC1EA9ED2B29C92F5E6AD466C`
- firmware: `1.02`
- hardware revision: `18`
- health: `OK`
- sample rate: `5 kHz`
- scan frequency: 약 `10 Hz`
- maximum range: `16 m`

### 3. Pure LiDAR Cartographer 구성 통합

사용자가 만든 `lidar_only_slam` 폴더의 Cartographer 2D 구성을 기반으로 다음을
통합했다.

- C1 드라이버
- `base_link -> laser` 정적 TF
- Cartographer 2D
- Cartographer occupancy grid
- 전용 RViz

Cartographer 설정은 다음 조건을 유지한다.

- IMU 사용 안 함
- wheel odometry 사용 안 함
- LaserScan 하나만 사용
- online correlative scan matcher 사용
- `provide_odom_frame = true`

### 4. 자동 설정 기능 추가

`scripts/run_mapping.sh`에 다음 기능을 넣었다.

- `/dev/slamtec_c1` 우선 감지
- CP210x `by-id`, `/dev/rplidar`, `/dev/ttyUSB0` fallback
- 직렬 포트 읽기/쓰기 권한 확인
- GUI에서는 `pkexec`, 터미널에서는 `sudo` 권한 요청
- 실제 `/scan` 메시지가 도착하는지 3초간 확인
- 정상 외부 드라이버가 있으면 재사용
- 데이터가 없는 stale SLLIDAR 프로세스 자동 정리
- 공식 `sllidar_ros2` overlay 자동 탐색
- 드라이버가 없으면 `.deps/sllidar_ws`에 공식 저장소 자동 clone/build
- 중복 매핑 실행을 runtime lock으로 차단

### 5. USB 재연결 문제와 수정

첫 자동화 버전은 `/scan`의 publisher count만 확인했다.

USB를 재연결하자 Linux 장치가 다음처럼 변경됐다.

```text
/dev/ttyUSB0 -> /dev/ttyUSB1
```

기존 드라이버는 죽은 포트를 잡은 채 ROS publisher endpoint만 남겼다. 새 실행은
이를 정상 발행자로 오판해 드라이버를 시작하지 않았고, Cartographer와 RViz만
중복 실행했다.

수정 내용:

- publisher count 대신 실제 LaserScan 메시지 수신 여부 확인
- udev 별칭 `/dev/slamtec_c1`을 launch에 그대로 전달
- symlink를 `readlink -f`로 불안정한 `ttyUSBX` 경로로 변환하지 않음
- stale SLLIDAR 프로세스 정리
- SLLIDAR node에 `respawn=True`, `respawn_delay=2.0` 적용
- 중복 실행 lock 추가

강제로 SLLIDAR 프로세스를 종료한 시험에서 2초 뒤 새 PID로 자동 재시작했고,
다시 health OK와 `/scan` 약 10 Hz가 확인됐다.

### 6. udev 영구 규칙

다음 규칙을 시스템에 설치했다.

```text
/etc/udev/rules.d/99-slamtec-c1.rules
```

동작:

- CP210x `10c4:ea60` 자동 접근 권한
- `/dev/slamtec_c1` symlink 생성

새 PC 또는 Jetson에서는 다음 명령을 한 번 실행해야 한다.

```bash
./scripts/install_udev_rule.sh
```

### 7. RViz 구성 수정

시스템 기본 `demo_2d.rviz`는 설치되지 않은 `cartographer_rviz/SubmapsDisplay`와
제3자 panel을 참조해 plugin load error를 냈다.

기본 RViz 플러그인만 사용하는 `config/lidar_only_mapping.rviz`를 추가했다.

표시 항목:

- occupancy map
- raw LaserScan
- scan-matched PointCloud2
- TF
- grid

## 최종 검증 결과

- shell script 문법 검사 통과
- Python launch 문법 검사 통과
- `ros2 launch ... --show-args` 통과
- C1 자동 포트 감지 확인
- C1 health OK
- `/scan` 약 10 Hz 확인
- `map -> odom -> base_link -> laser` TF 확인
- `/map` 0.05 m 해상도 발행 확인
- Cartographer trajectory 및 submap 생성 확인
- RViz plugin error 제거 확인
- 중복 실행 차단 확인
- SLLIDAR 강제 종료 후 자동 respawn 확인

## 최종 실행 명령

```bash
cd /home/data1/isaac_sim_ros/python_codes/lidar_only_slam
./scripts/run_mapping.sh rviz:=true
```

맵 저장:

```bash
./scripts/save_map.sh ./maps/lab_map
```

## 참고 사항

- LiDAR-only SLAM은 특징이 적은 긴 복도나 대칭 공간에서 드리프트가 커질 수 있다.
- 실제 로봇 장착 위치가 `base_link`와 다르면 `laser_x/y/z/roll/pitch/yaw`를 반드시
  실제 치수에 맞춰야 한다.
- Jetson에 이 폴더만 복사한 경우 최초 실행 시 공식 `sllidar_ros2`를 자동으로
  clone/build하므로 네트워크, `git`, `colcon`이 필요하다.
- 현재 실행 중인 매핑을 다시 실행하면 중복 방지 메시지가 출력되는 것이 정상이다.

