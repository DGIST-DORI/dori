# 검증 — 2026-09-08

## 완료

- 전체 colcon 빌드: 15개 패키지 성공 (`log/final_build.log`).
- 바퀴 odometry/피드백 gtest: CTest 집계 7개, 오류·실패 0. CSV/지도/속도 계약 unittest 2개 성공 (`log/final_tests.log`).
- ROS 도메인 92의 실제 supervisor/drive + 가짜 액션 서버 통합 시험: 8개 항목 성공. SI→정규화→바퀴 rad/s, joystick idle와 AUTO 공존, 센서 단절 정지, cached ROS 상태와 무관한 CAN 피드백 단절 정지, 목표 교체·취소, 늦은 액션 승인 및 늦은 LLM 결과 차단, 비상 정지, 최종 watchdog. `navigation_integration_results.json`.
- ROS 도메인 93의 **실제 Nav2 + 실제 supervisor/drive/wheel odometry + 소프트웨어 바퀴·라이다**: 지도 로딩, AMCL 초기화, lifecycle, TF·타입·단위·발행자 계약 검사 후 이름 목표 SUCCEEDED와 바퀴 정지 확인. `real_nav2_software_results.json`, `software_nav2_preflight.json`. 종료 위치는 Nav2 허용 오차 안에 있으며 정밀 도킹 시험은 아님.
- 실제 C1 라이다: 38개 scan, 약 9.9Hz, 유효 거리 24,673개, frame=laser. `hardware_lidar_results.json`. 측정 후 시험용 드라이버 종료.
- USB 장치: C1(`/dev/slamtec_c1`), FTDI 서보, Arduino IMU, CANable2 식별.

## 실기에서 남은 조건

- 현재 `can1` 미생성. `sudo -n true`는 비밀번호 필요로 실패. 통합 실행 파일이 로컬 터미널에서 CAN 준비를 수행하도록 구성되어 있으나 이번 세션에서 실제 CAN 수신/모터 주행은 검증하지 못함.
- 실제 저장 지도와 해당 지도 목적지 CSV 미제공. 제공된 번들의 예시 지도/소프트웨어 시험 지도는 실기 지도에 사용하지 않음.
- 실제 초기 위치, 바퀴 반지름·간격/기어비·회전 방향, 변형 후 주행 자세, 로봇 외곽·라이다 장착 TF는 실측 검증 필요. 기본 수치는 기존 코드 값이며 교정 결과가 아님.
- 온라인 LLM API 인증/자연어 응답은 미시험. 등록 이름 직접 전달과 지연된 LLM 응답 폐기는 오프라인에서 검증.

## 재현

```bash
cd /home/dori/robot_ws
source scripts/env.sh
colcon test --packages-select robot_drive --event-handlers console_direct+
colcon test-result --test-result-base build/robot_drive --verbose
python3 -m unittest discover -s tests -p test_navigation_contracts.py
ROS_DOMAIN_ID=92 ROS_LOCALHOST_ONLY=1 python3 tests/integration_navigation.py
ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1 python3 tests/real_nav2_software_robot.py
# 실기 스택을 실제 장치와 시작한 뒤:
./scripts/check_navigation.sh --output docs/current_hardware_preflight.json
```

도메인 92/93 시험은 물리 모터 드라이버를 실행하지 않습니다. `check_navigation.sh`는 상태 조회만 하며 주행 명령을 발행하지 않습니다. C++ TF 검사기는 Humble에서 Python API에 없는 publisher GID를 사용해 `odom→base_link` 발행자를 검증합니다.


## 2026-09-09 고정 기준각 변신

`robot_transform` 및 DXL 드라이버 빌드, C++ 목표 계산 테스트, 격리 ROS 통합 테스트 통과. 실제 하드웨어는 구동하지 않음. 설정과 상세 결과: [TRANSFORM_REFERENCE.md](TRANSFORM_REFERENCE.md).
