> 2026-09-09 업데이트: 사용자 좌회전·앞부분 들기 시험으로 축 방향을 확인했고, 몸체 고정 및 위치 추정(x=0, y=0.10, z=0.10 m)을 반영했습니다. 보정 설정은 `src/robot_mapping/config/imu_calibrated.yaml`, 실행은 `./scripts/start_mapping_imu.sh`입니다. 아래 초기 조사 기록의 “장착 방향 미확정”은 당시 상태입니다. 현재 구성은 라이다+보정 IMU이며 wheel odom은 SLAM 입력에서 제외합니다. 위치는 사용자 추정값입니다.

# SLAM 센서 점검 — 2026-09-09

## 정지 재측정

사용자가 정지 상태임을 확인한 뒤 약 30초간 읽기 전용 측정했습니다.

- wheel odometry 약 100Hz, 단조 증가 timestamp. 변위 약 0.045mm, yaw 변화 약 -0.028°. 순간 속도는 최대 약 0.0094m/s, 0.099rad/s였으므로 미세 진동/엔코더 양자화 영향은 존재합니다.
- /odom과 odom→base_link TF 차이 0, sole TF owner wheel_odometry_node, CAN 피드백 신선도 검사 통과.
- IMU 약 82.3Hz. 가속도 평균 [-0.00774, 0.00674, -9.61652]m/s².
- 정지 자이로 평균 [0.12828624, -0.00557299, -0.02409203]rad/s (약 [+7.35, -0.32, -1.38]°/s). 전반/후반 평균도 비슷해 무시할 수 없는 정지 바이어스가 관측됐습니다.
- orientation_covariance[0]=-1: 절대 자세를 제공하지 않음. 단위 quaternion을 유효한 자세로 사용하면 안 됩니다.
- 정지 측정만으로 이동 중 슬립, 거리 스케일, 실제 좌우 회전 부호를 검증할 수 없습니다.

원자료 요약: imu_stationary_20260909.json, odom_audit_20260909.json.

## 적용 방향

가속도만 이중 적분하는 IMU-only odometry로 교체하지 않습니다. 바이어스·중력 제거·축 방향 오차가 위치 추정에 누적됩니다. 현재는 라이다 스캔 정합에 우선 의존하고, 보정된 IMU의 가속도/각속도를 Cartographer에 직접 입력하는 구성을 준비했습니다. 이는 wheel+IMU EKF odometry를 구현했다는 의미가 아닙니다.

[Cartographer 공식 설정](https://google-cartographer-ros.readthedocs.io/en/latest/configuration.html)은 IMU를 사용할 때 tracking_frame을 IMU 위치에 두도록 요구합니다. 추가 모드는 tracking_frame=imu_link이며 base_link→imu_link 정적 TF에 측정한 장착 위치/회전을 사용합니다. [센서 좌표계 준비](https://github.com/cra-ros-pkg/robot_localization/blob/rolling-devel/doc/preparing_sensor_data.rst)도 프레임/단위 확인의 필요성을 설명합니다.

IMU의 가속도 Z가 음수라는 사실만으로 yaw 장착 방향은 결정할 수 없습니다. 거꾸로 장착되었거나 펌웨어 축/부호 관례가 다를 가능성을 확인해야 합니다. 기존 body_pitch_node는 센서 gx와 atan2(ay,-az)를 쓰므로 원본 IMU를 일괄 회전시키면 기존 자세 제어에도 영향을 줍니다. 따라서 /imu/data_raw는 그대로 두고 /imu/mapping에 전용 바이어스 보정 스트림을 추가했습니다.

## 지금 실행 가능한 라이다 중심 매핑

기존 매핑 터미널에서 Ctrl+C 후:

```bash
cd /home/dori/robot_ws
./scripts/start_mapping.sh --mapping-odometry lidar
```

이 모드에서는 Cartographer use_odometry=false입니다. 바퀴 /odom은 제어·진단을 위해 계속 발행하지만 SLAM 측정 입력으로 사용하지 않습니다. odom→base_link는 기존 wheel 노드만 소유하며 Cartographer는 map→odom을 보정합니다. 따라서 /odom 토픽 자체의 슬립을 제거하는 모드는 아닙니다. 지도/라이다 정합의 차이를 비교하는 매핑 모드입니다. 긴 복도·특징 부족 환경에서 라이다만으로도 오차가 생길 수 있습니다.

기존 바퀴 odometry 사용 모드:

```bash
./scripts/start_mapping.sh --mapping-odometry wheel
```

라이다가 전진 방향과 일치하므로 laser_yaw=0을 유지했습니다. 위치 x/y/z와 roll/pitch는 실측값이 필요합니다. 고정 장착 yaw와 세계 좌표 기준 절대 heading은 다른 개념이며 yaw=0 설정이 세계 heading을 고정하지 않습니다.

## IMU 사용 전 남은 확인

1. IMU가 base_link와 고정된 위치에 있는지, 움직이는 관절에 붙어 있는지 확인. 관절 장착이면 정적 TF를 사용하면 안 됩니다.
2. 센서 축 표시/펌웨어 관례와 실제 장착 위치 확인. 정지 중력만으로 수평 yaw를 확정할 수 없습니다. 방향을 알고 시행한 좌회전과 전방 기울임 측정 또는 장착 축 확인이 필요합니다.
3. 측정한 IMU→base 좌표 회전이 중력 방향, 실제 좌회전 양의 angular.z, 전방 움직임 축을 만족하는지 확인.
4. 예열 후 정지 자이로 바이어스를 재확인. 현재 측정값을 템플릿에 기록했지만 자동으로 장착 확인 완료 처리하지 않았습니다.

`src/robot_mapping/config/imu_calibration.yaml`의 verified=false 상태에서는 IMU 매핑 시작이 거부됩니다. xyz_m/rpy_rad/gyro_bias_rad_s를 검증한 뒤 verified=true로 설정하고 빌드하면 다음을 사용할 수 있습니다.

```bash
./scripts/start_mapping.sh --mapping-odometry lidar \
  --imu-calibration /home/dori/robot_ws/src/robot_mapping/config/imu_calibration.yaml
```

현재 위 IMU 명령은 미검증 보정값 때문에 의도적으로 거부됩니다. 임의로 verified만 바꾸지 마세요. /imu/mapping은 stale/역순/비유한 샘플을 버리고 sensor-frame bias를 뺍니다. Cartographer가 static TF로 올바른 좌표 변환을 수행합니다. IMU를 EKF와 Cartographer에 중복 융합하는 구성은 추가하지 않았습니다.

## 검증 범위

빌드, wheel/lidar/IMU 구성 조합의 Lua 렌더링, TF 소유권 설정, 미검증/비유한 보정값 차단을 테스트했습니다. 실행 중인 실제 매핑은 중단하거나 변경하지 않았습니다. 보정 IMU를 이용한 실기 지도 품질과 새 라이다 중심 모드의 이동 중 지도 품질은 아직 비교 측정하지 않았습니다.
