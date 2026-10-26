# 실기 주행 구조와 인터페이스

실행 안내는 [사용자 문서](../user/real-robot.md), 입력 변환은 [역모델·TTA](real-robot-motion-interpreter.md)를 참고한다. 경로는 저장소 루트 기준이다.

## 모듈 경계

| 구성 | 경로 | 책임 |
| --- | --- | --- |
| 통합 자율주행 | `ros2_ws/scripts/autonomy.py` | 기존 구성 검사·재사용, 무게임패드 실행, 소유 프로세스 종료 |
| 매핑/선택형 실행 | `ros2_ws/scripts/robot_stack.py` | 새 구동 세션, LiDAR 추정, Cartographer 또는 Nav2, 웹 |
| 실제 하드웨어 기동 | `ros2_ws/scripts/run_robot_control.sh`, `src/robot_bringup` | CAN·시리얼·컨트롤러 준비와 기존 구동/짐벌 연결 |
| LiDAR odometry | `ros2_ws/src/robot_mapping/lidar_odometry/core.py`, `scripts/lidar_odometry_node.py` | point-to-line 정합, keyframe, 퇴화/겹침/잔차 검사, odom·TF |
| 매핑 | `ros2_ws/src/robot_mapping/launch/lidar_only_cartographer.launch.py` | 외부 LiDAR odometry를 사용하는 2D Cartographer |
| 위치 추정·경로 | `ros2_ws/src/robot_navigation/launch/real_nav2.launch.py`, `config/nav2_real.yaml` | AMCL, Smac Hybrid, Regulated Pure Pursuit, smoother, lifecycle |
| 방향 완화 planner | `ros2_ws/src/robot_navigation/src/relaxed_heading_planner.cpp` | 최종 yaw를 강제하지 않는 접근 방향 후보 계획 |
| 목표 상태·재시도 | `ros2_ws/src/robot_navigation/scripts/named_goal_bridge.py` | 목표 직렬화, 승인/취소, 도착 검증, ABORTED 재시도 |
| 실제 이동 명령 | `nav_drive_bridge.py`, `motion_interpreter.py`, `reverse_clearance.py` | 센서/TF/구동 상태 검사, 역모델·시각 정렬·온라인 보정, 후방 여유 검사 |
| 공통 저수준 제어 | `ros2_ws/src/robot_drive`, `robot_supervisor`, `cubemars_hardware` | 수동/AUTO 선택, 가감속·토크·상태 보호, CAN MIT 구동 |
| 기구·짐벌 | `ros2_ws/src/robot_transform`, `DynamixelSDK`, `imu_serial` | DXL 위치/피드백, 기존 변형 제어, 몸체 pitch·짐벌 추종 |
| 웹 | `ros2_ws/src/robot_navigation/dori_web` | ROS 상태 투영, 관리자/사용자 API, 초기 위치·자동 정합, 이름 목표, STT/대화/TTS |

`robot_msgs`, `robot_input`, `robot_error`와 벤더 드라이버도 실제 기동 의존성으로 함께 포함한다. 기존 변형 제어는 주행 supervisor와 연결되어 있어 유지했다. 별도 셀 데모·토크 sweep·폐기한 IMU 위치 추정·Isaac/restamp 도구는 포함하지 않는다. 공통 제어기의 선택적 wheel torque servo는 기본 비활성 상태로 유지한다.

## 데이터 흐름과 TF 소유권

```text
/scan ── LiDAR scan matching ── /odom + odom→base_link
             ├─ Cartographer (매핑): /map + map→odom
             └─ 저장 지도 + AMCL (주행): map→odom

/imu/data_raw ── body_pitch ── servo3_pitch_follower ── DXL 짐벌

웹 좌표/이름/상대 목표 → named_goal_bridge → Nav2
  → /nav/cmd_vel_raw → velocity_smoother → /nav/cmd_vel [SI]
  → nav_drive_bridge + MotionInterpreter → /auto/cmd_vel [normalized]
  → supervisor → /drive/cmd_vel → drive_controller → ros2_control → CAN
```

`odom→base_link`는 `lidar_odometry` 하나가 발행한다. wheel odometry 노드는 진단용 소스/검사와 함께 남아 있지만 표준 실행에서는 끈다. `base_link→laser`는 odometry launch가 제공하며 xyz=0·yaw=π가 현재 장착 기본값이다. 매핑과 주행은 같은 연속 odometry를 사용하되 `map→odom` 발행자는 각각 Cartographer/AMCL 하나다. IMU는 기본 위치 추정에 융합하지 않는다.

## 단위와 상태 계약

| 토픽 | 타입·단위 | 의미 |
| --- | --- | --- |
| `/scan` | LaserScan, m/rad, frame `laser` | 실제 측정 타임스탬프. 재발행 시각으로 덮어쓰지 않음 |
| `/odom` | Odometry, `odom`→`base_link`, m/rad 및 m/s·rad/s | LiDAR 기반 몸체 이동 |
| `/goal_pose`, `/relative_goal_pose` | PoseStamped, frame `map` | 목표 브리지만 Nav2 액션으로 변환 |
| `/NAVIGATION_MODE` | Int32, 0/1 | AUTO 정지/허용 |
| `/navigation/goal_active` | Bool | 승인된 활성 목표가 있을 때만 구동 허용 |
| `/nav/cmd_vel` | Twist, m/s·rad/s | 계획한 몸체 속도 요구 |
| `/auto/cmd_vel`, `/drive/cmd_vel` | Twist, 무차원 −1…1 | 조이스틱과 같은 정규화 구동 입력 |
| `/bldc_mit_speed_cmd` | MitCommand, rad/s·Nm | 논리 좌/우 바퀴 목표와 보상 |
| `/dynamic_joint_states` | DynamicJointState | 실제 CAN position/velocity/feedback_age |
| `/drive/wheel_control` | DynamicJointState | 제한기 이후 target_velocity, measured_velocity(rad/s), compensation_torque(Nm) |
| `/navigation/halt` | Bool | AUTO 정지 시 남은 제한기 출력 정리 |
| `/navigation/motion_interpreter` | JSON String | 요구·적용 입력·엔코더·응답 계수·학습 표본 수 |
| `/navigation/retry_status` | JSON String | 재시도 상태·횟수·남은 시간 |
| `/localization/auto_alignment` | JSON String | 정합 점검·보정 횟수·일치율·보류 이유 |

논리 모터 ID 1=left, 2=right이며 **물리 CAN 주소와 구분**한다. 현재 URDF는 left=CAN 2·direction_sign +1, right=CAN 1·direction_sign −1이다. DXL 논리 모터 3/4/5는 실제 ID 1/2/3에 대응하며 5가 pitch 짐벌이다. 추가적인 좌우/센서 반전을 상위 명령에 넣지 않는다.

## 보호와 도착 정책

가감속·토크 제한, CAN watchdog/feedback_age, supervisor, ESTOP은 공통 저수준 제어에 남아 있다. 자동 해석기는 그 이후 실제 적용 입력과 센서 응답을 관측하며 제한을 해제하지 않는다. 추가 wheel torque servo는 `wheel_servo.enabled: false`다.

Nav2 요구 상한은 0.3m/s·1.2rad/s다. 기구의 정규화 스케일 1.72m/s·7rad/s와 구분한다. 일반 도착은 Nav2 30cm, 목표 브리지 재확인 35cm이며 상대 목표는 각각 10cm/15cm다. 최종 yaw는 강제하지 않는다. Smac Hybrid의 최소 반경 0.7m, 곡률·장애물 검사, 후진 복구의 충돌 검사는 유지한다.

오도메트리와 TF는 서로 다른 DDS 스트림이므로 같은 측정 시각으로 짝지은 최신 자료를 사용한다. 아직 TF가 안 온 단일 새 메시지 때문에 유효한 직전 쌍을 버리지 않지만 신선도 제한은 늘리지 않는다. 실제 CAN 피드백의 유효성은 JointState 헤더가 계속 갱신되는지만으로 판단하지 않는다.

## 웹·위치 추정 경계

`dori_web/bridge.py`가 ROS 실행 스레드에서 명령을 처리하고 HTTP는 큐를 사용한다. 제어 소유권/heartbeat, 만료 요청 폐기와 늦은 액션 승인 취소를 유지한다. 7070은 관리자 초기 위치·임의 좌표·목표 편집 API를 제공하지 않는다. Gemini는 허용된 목적지 ID 또는 전진 거리를 반환하고 실제 좌표는 서버에서 결정한다.

수동 초기 위치 탐색(`localization.py`)은 대략적인 클릭 주변 ±1.5m·전체 방향을 검색하고 LiDAR 기준 재연결 및 AMCL 정지 갱신을 수행한다. 주기 자동 정합(`auto_alignment.py`)은 현재 위치 주변 0.6m·±15°를 탐색하며 LiDAR odometry를 초기화하지 않는다.

자동 정합은 정지 상태 1초, 세 스캔 후보 차이 8cm·3° 이내, 점수 ≥0.65, 지도 25cm 이내 점 비율 ≥75%, 개선량 ≥0.035와 후보 구별 조건을 검사한다. 적용은 최대 30cm·8°이며 AMCL과 화면 TF 반영을 확인한다. 작은 차이나 유의미한 개선이 없으면 현재 위치를 유지하고, 불확실한 후보는 보류한다. 최신 수동 명령·이동·지도 변경은 계산 중인 자동 후보보다 우선한다.

## 설정 파일

- `robot_drive/config/kinematics.yaml`: R=0.234m, L=0.184m, 정규화 스케일.
- `robot_drive/config/drive_params.yaml`: 공통 구동, 피드백·토크 제한. `robot_bringup/launch/system_real.launch.py`의 명시적 override도 함께 확인한다.
- `robot_navigation/config/motion_interpreter.yaml`: 응답 gain·출발 입력·지연·PI·arc 정책.
- `robot_navigation/config/nav2_real.yaml`: AMCL, costmap, planner/controller, 도착 범위.
- `robot_navigation/config/navigate_basic.xml`, `navigate_relative.xml`: 진행 실패와 후진 복구.
- `robot_mapping/config/lidar_odometry.yaml`: 스캔 정합 품질·keyframe·이동 검증.
- `robot_bringup/config/cubemars_mit.urdf.xacro`: CAN 주소·방향·펌웨어 MIT 설정.
- `robot_transform/config/`: 기존 변형·DXL 연결.

위 경로는 모두 `ros2_ws/src/` 아래다. 본체/짐벌의 자세 추종 값은 `system_real_with_imu.launch.py`에 있다. 자세 변화에 따른 동적 LiDAR 외부파라미터와 빔별 deskew는 아직 구현하지 않았다.
