# 실제 로봇 통합 작업공간

전체 실행 순서와 복사용 명령: [실행명령어.md](실행명령어.md)

기준 위치는 `/home/dori/robot_ws`입니다. 2026-09-08 Isaac/LLM 압축 파일을 풀고 기존 CAN·서보·IMU·라이다 코드와 통합했습니다. 원본 및 수정 전 백업은 보존했습니다.

`LLM → 이름 목적지 → Nav2 → SI 속도 → 정규화 속도 → supervisor → 바퀴 rad/s → CAN` 경로를 연결했습니다. 실제 환경 지도, 초기 위치, 기구 치수의 실측은 별도로 필요합니다. 소프트웨어 테스트 결과가 실물 주행 검증을 의미하지는 않습니다.

## 실행

```bash
cd /home/dori/robot_ws
./scripts/build.sh
# 장치 상태만 검사
./scripts/run_robot_control.sh --check --no-joystick
# 지도 생성: 제어 + 라이다 + 바퀴 odometry + Cartographer
./scripts/start_mapping.sh --rviz
# 조이스틱이 없으면 --no-joystick 추가
```

통합 시작 명령은 모터·서보 제어를 켭니다. 이미 실행 중인 제어가 있으면 중복 실행을 거부합니다. CAN 준비 시 로컬 터미널에서 sudo 비밀번호가 필요할 수 있습니다. 라이다 위치는 `--laser-x`, `--laser-y`, `--laser-z`(m), `--laser-roll`, `--laser-pitch`, `--laser-yaw`(rad)로 지정합니다. 기본 0은 임시값입니다.

다른 터미널에서 지도를 저장하고 목적지를 지정합니다.

```bash
cd /home/dori/robot_ws
./scripts/save_map.sh /home/dori/robot_ws/maps/site
./scripts/edit_points.sh /home/dori/robot_ws/maps/site.yaml /home/dori/robot_ws/maps/site.points.csv
```

매핑 터미널에서 Ctrl+C로 세션을 종료한 뒤 저장 지도 기반 주행을 시작합니다.

```bash
./scripts/start_navigation.sh --map /home/dori/robot_ws/maps/site.yaml \
  --points /home/dori/robot_ws/maps/site.points.csv --rviz
# 현재 지도상의 위치를 지정: x(m) y(m) yaw(도). 아래 값은 형식 예시입니다.
./scripts/set_initial_pose.sh 0.0 0.0 0.0
./scripts/check_navigation.sh
./scripts/navigate.sh '목적지명'
./scripts/stop_navigation.sh
```

초기 위치에는 실제 현재 위치를 입력하거나 RViz의 **2D Pose Estimate**를 사용합니다. 이동은 `navigate.sh`의 이름/텍스트 경로를 사용합니다. RViz의 직접 목표는 이름 목표 활성화 계약을 충족하지 않아 구동이 차단됩니다.

정확한 CSV 목적지 이름은 API 없이 동작합니다. 자연어 해석은 **시작 터미널의** `OPENAI_API_KEY`가 필요합니다. 키를 코드에 저장하지 않습니다. 실패·허용되지 않은 LLM 응답은 주행 목표로 전달하지 않습니다. 온라인 API 호출은 이번 검증에서 수행하지 않았습니다.

`stop_navigation.sh`는 목표 취소와 AUTO 정지를 요청하며 수동 모드로 자동 전환하지 않습니다. 하드웨어 비상 정지 상태도 자동 해제하지 않습니다. 세션 Ctrl+C는 해당 세션이 시작한 자식 프로세스를 종료합니다. 로그는 `log/session_*/`에 남습니다.

## 설정과 구성

- 공통 기구·속도 스케일: `src/robot_drive/config/kinematics.yaml`. 현재 기존 코드 값은 반지름 **0.234m**, 바퀴 간격 **0.184m**, 정규화 1당 **1.72m/s**, **7rad/s**입니다. 실제 치수·기어비를 확인해 수정한 뒤 빌드하세요.
- Nav2 제한/로봇 외곽: `src/robot_navigation/config/nav2_real.yaml`. 현재 제한 0.3m/s, 0.8rad/s. `robot_radius: 0.30`은 실측 외곽이 아닙니다. 두 costmap의 외곽을 실제 로봇에 맞춰야 합니다.
- 바퀴 odometry: `src/robot_drive/config/odometry.yaml`. 실측 위치의 차분·원호 적분, MIT 8π 순환 처리. 개별 모터 CAN 피드백이 오래되면 odom 발행 및 구동을 차단합니다. encoder 영점을 실행 중 바꾸면 odometry도 재시작하세요.
- `src/robot_bringup`, `cubemars_hardware`, `DynamixelSDK`, `imu_serial`: 실제 장치 제어.
- `src/robot_mapping`: Cartographer. `src/robot_navigation`: 실제/Isaac Nav2, LLM, 목적지 편집기 및 구동 연결.
- 실제 실행은 공통 `/tf`, `/scan`, `/odom`, 실제 시계를 사용합니다. Isaac/restamp/가짜 odom 도구는 실제 launch에 포함하지 않습니다.
- 지도와 목적지 CSV가 없거나 좌표가 지도 밖/점유/미확인 셀이면 주행 시작을 거부합니다. CSV 열은 `name,x,y,yaw_deg,frame_id`, frame은 `map`입니다. 중심 셀 검사는 로봇 전체 외곽의 통과 가능성을 보장하지 않으며 costmap이 이를 판단합니다.

자세한 인터페이스는 [CONTRACTS.md](docs/CONTRACTS.md), 검증 범위는 [VALIDATION.md](docs/VALIDATION.md), 원본 위치는 [SOURCES.md](docs/SOURCES.md)를 참고하세요. 실제 지도·장착값을 입력한 후 실행 중 `check_navigation.sh`가 통과해야 주행 조건이 갖춰집니다.
