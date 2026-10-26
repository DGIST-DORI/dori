# 실기 주행 정리본: 반영 범위와 검증

2026-10-26, Ubuntu 22.04.5 aarch64 / Python 3.10.12 / ROS 2 Humble에서 확인했다.
실행법은 [운영 안내](../user/real-robot.md), 입력 모델은 [역모델·TTA](real-robot-motion-interpreter.md)에 있다.

## 메인 저장소에 반영하는 단위

기준은 [DGIST-DORI/dori](https://github.com/DGIST-DORI/dori)의
`main` 커밋 `d4cc1ae079082ef5af94583ce684155c39f58c28`이다.
반영 브랜치는 `realrobot_ws`이다.

원본 `robot_ws`를 먼저 복제한 뒤 복제본만 정리하고 메인 저장소의 `ros2_ws/` 구조로 배치했다.
원본 소스·설정·도구·문서·지도 761개 파일의 SHA-256은 작업 전후 모두 일치했다.
원본의 빌드 산출물·로그·실험 자료는 원본에 남아 있다.

| 위치 | 포함 범위 |
| --- | --- |
| `ros2_ws/src/robot_*` | 현재 실기 제어, supervisor, 입력/메시지, LiDAR odometry, Cartographer, Nav2, 웹 |
| `ros2_ws/src/cubemars_hardware` | Dori MIT CAN 구현과 통신 장애 검사 |
| `ros2_ws/src/imu_serial` | IMU 입력, pitch 추정, 몸체 안정화, 짐벌 추종 |
| `ros2_ws/src/DynamixelSDK`, `sllidar_ros2` | 현재 실행에 필요한 벤더 소스와 라이선스; DXL 제어 수정 포함 |
| `ros2_ws/scripts` | 설치·빌드, 통합 실행, 상태 점검, 지도 저장, 정지 |
| `ros2_ws/tools` | 수동 주행 기록·응답 모델 재보정·센서 시각 진단 |
| `ros2_ws/tests` | 유지 기능의 회귀 검사와 하드웨어 없는 통합 시험 |
| `ros2_ws/maps` | 현재 현장 참고 지도 한 세트와 이름 목표 예제 |
| `docs/user`, `docs/dev` | 현재 실행법·구조·모델·검증 결과 |

기존 메인 저장소의 `dori_*`, `web/`, 대화·인지·Behavior Tree 코드는 유지한다.
실기 구성은 자체 8080/7070 웹과 Nav2를 실행하는 별도 실행 프로필이다.
기존 HRI/BT의 `/dori/...` API를 이 주행 경로에 연결하는 통합은 포함하지 않는다.
같은 ROS 도메인에 다른 구동/odometry/Nav2 스택을 동시에 띄우지 않는다.

이전 IMU 위치 추정, Isaac 전용 launch, 토크 sweep, 단발 모터 시험, 셀 데모,
중복 지도·백업·과거 결과 보고서는 정리본에서 제외했다.
변형 제어·짐벌·모터 보호는 실제 기동 의존성이므로 유지했다.
공통 제어기의 선택적 wheel torque servo와 wheel odometry는 소스/검사와 함께 남지만
표준 실행에서는 비활성이다. 실행되는 저수준 제어 알고리즘과 보호값은 이 정리 작업에서 변경하지 않았다.

`build/`, `install/`, `log/`, 로컬 목표 수정 파일과 API 키는 커밋 대상이 아니다.
새 작업공간에서 별도로 빌드했고, 실행 스크립트는 자기 위치에서 작업공간을 찾는다.
원본 작업공간을 source하거나 원본의 목표 파일에 쓰지 않는다.

## 검증 결과

Nav2는 설치 버전 `1.1.20`, Cartographer ROS는 `2.0.9002`를 사용했다.
아래 통합 시험은 ROS 도메인 94/95와 localhost에 격리했다.
실제 CAN/DXL/조이스틱 장치 노드를 시작하거나 로봇에 주행 명령을 보내지 않았다.

| 검사 | 결과 |
| --- | --- |
| 깨끗한 작업공간 빌드 | 실기 의존성 15개 패키지 성공; 기존 install 재사용 없음 |
| Python 단위/계약 검사 | 94개 통과; 전체 하드웨어 launch 생성 검사 포함 |
| CTest | CAN 통신 장애, wheel servo, wheel odometry 3개 테스트 실행 모두 통과 |
| launch/helper 조회 | 실제/IMU launch, Nav2 인자, 통합 실행 도움말, IMU 실행 파일 확인 |
| 코드 문법 | 추가 Python 85개, shell 18개, package/plugin/xacro XML 17개 확인 |
| 메인 topic-lint | 종료 코드 0; 경고 출력은 기준 main과 동일 |
| 수동 응답 재적합 | 보존한 원시 기록으로 전진·회전 계수, 지연, 학습/검증 오차 재현 |

LiDAR SDK 빌드에는 기존 SDK의 zero-length array 관련 컴파일 경고가 있다.
현재 장치의 시스템 `rosdep` source 목록은 초기화되지 않아 별도 임시 source 목록으로
의존성을 확인했다. `rosdep check`에서 미설치로 나온 apt 항목은 `python3-serial` 하나다.
현재 Python에서는 사용자 설치된 pyserial 3.5를 정상 import한다.
빌드와 실행 시험은 이 장치에 이미 설치된 의존성으로 수행했다.
새 장치용 설치 절차에는 `rosdep init/update`와 `can-utils` 준비를 명시했고,
누락되어 있던 IMU·joy·forward_command_controller·ament_index_python 의존성 선언을 보완했다.
새 OS에서 패키지를 설치하는 전체 과정까지 검증했다는 뜻은 아니다.
새로 작성하거나 수정한 파일의 공백 검사는 통과했다. 전체 가져오기 diff에는
원본 벤더 SDK와 유지한 제어 파일의 기존 trailing whitespace 경고가 남아 있다.

## 격리된 ROS 통합 시험

소프트웨어 로봇은 실제 LiDAR odometry·Cartographer 또는 AMCL/Nav2·주행 제어·웹 API를 실행한다.
센서와 모터 응답만 합성한다. 특히 주행 모델은 현재 보정식으로 만든 결정론적 모델이므로,
이 결과는 연결·상태 전이·단위 계약에 대한 검증이다. 실물의 미끄럼·마찰·지연 정확도를 입증하지 않는다.

| 시나리오 | 관측 결과 | 기록 |
| --- | --- | --- |
| LiDAR 매핑→지도 저장 | 234 scans, 알려진 셀 46,982개, 점유 셀 1,315개, YAML/PGM 저장 성공 | [mapping.json](evidence/real_robot/mapping.json) |
| 최종 방향 완화 | 150° 목표 방향에서 계획 길이 4.627m→0.800m, 원형 정렬 없이 25.2cm 오차로 종료 | [heading_arrival.json](evidence/real_robot/heading_arrival.json) |
| 상대 목표·일시 장애물 재시도 | 1m 목표, 5.51초 대기 후 동일 목표 재개, 최종 오차 8.9cm | [relative_retry.json](evidence/real_robot/relative_retry.json) |
| 정지 중 자동 재정합 | 주입 오차 (18cm, 8cm, 0.06rad)에서 최종 위치 오차 약 1.54cm; 이동 0, odom 원점 유지 | [auto_alignment.json](evidence/real_robot/auto_alignment.json) |
| 전방 막힘 후진 복구 | 약 36.4cm 후진 후 전진 재개, 목표 오차 25.2cm로 종료 | [reverse_recovery.json](evidence/real_robot/reverse_recovery.json) |
| 후방 장애물 | 후진·누적 이동 0m 유지, 3회 재시도 후 목표 실패로 종료 | [blocked_rear.json](evidence/real_robot/blocked_rear.json) |

매핑 시험의 최종 LiDAR odometry 위치 오차는 약 0.6mm였지만 `map→base_link` 위치 오차는
19.1cm였다. 합성 환경의 값이며 실물 지도 정밀도로 인용하지 않는다.
주행 시험은 웹 정지 명령, 도착 후 출력 정지, 제어 탭 heartbeat 만료도 검사한다.
상대 명령 시험의 intent는 `--offline-intent` 고정 fixture다. 실제 사용자 포트의
목표 API부터 Nav2까지 검증하며, Gemini/STT를 호출한 시험은 아니다.

재현은 저장소의 `ros2_ws`에서 다음 순서로 한다. 도메인 95 시험들은 같은 테스트용 포트를
사용하므로 순차 실행한다. 출력은 `log/`에 저장하며 다음 시나리오가 같은 파일을 덮어쓸 수 있다.

```bash
./scripts/test.sh
source scripts/env.sh
export ROS_LOCALHOST_ONLY=1 OPENBLAS_NUM_THREADS=1

ROS_DOMAIN_ID=94 python3 tests/integration_mapping.py
export ROS_DOMAIN_ID=95
python3 tests/integration_lidar_web.py --heading-test
python3 tests/integration_lidar_web.py --relative-test --retry-test --goal-x 1.0 --offline-intent
python3 tests/integration_lidar_web.py --auto-alignment-test
python3 tests/integration_lidar_web.py --reverse-recovery
python3 tests/integration_lidar_web.py --reverse-recovery --blocked-rear
```

매핑 출력은 `log/mapping_validation.json`, 자동 정합은 `log/auto_alignment_validation.json`,
다른 주행 시나리오는 `log/lidar_web_navigation_results.json`이다.
일반 주행 시나리오의 상세 시계열은 `log/lidar_web_navigation_trace.json`에 기록된다.

## 실물 적용 시 확인할 항목

이번 작업은 원본을 보존한 저장소 정리와 새 경로에서의 재빌드/소프트웨어 검증이다.
최신 설정의 실물 냉간 기동·주행, 실제 바닥/하중에서의 곡률·정지 거리와 후진 응답은 이번에 재시험하지 않았다.
현재 입력 모델은 수동 전진·곡선 기록으로 보정했으며 후진 전용 보정은 없다.
수동 기록의 검증 MAE는 전진 약 0.0435m/s, 회전 약 0.1014rad/s다.
0.5초 차분 창이 겹치는 표본이므로 독립 표본 통계로 보지 않는다.

새 작업공간으로 실행하려면 기존 실행기를 종료하고 새 경로의 통합 스크립트를 시작한다.
기존 노드 재사용 기능만으로는 실행 중인 코드가 교체되지 않는다.
초기 위치, LiDAR와 지도 일치, 주행 gate, 저속 전진/완만한 곡선/정지 순서로 확인한다.
목표 도착 방향은 참고값이며 정확한 최종 yaw를 맞추는 구성이 아니다.

외부 음성 서비스·HTTPS·마이크 권한·브라우저 TTS는 실제 사용자 장치에서 확인해야 한다.
이번 정리 중 API 키로 원격 요청을 보내거나 기존 HTTPS 설정을 바꾸지 않았다.
브라우저 회귀 도구 `tests/browser_voice_retry.py`는 별도 Firefox Marionette와
`marionette_driver`가 필요하며 이번 검증에서는 실행하지 않았다.

짐벌은 IMU pitch를 추종하지만 동적인 LiDAR 외부파라미터와 빔별 deskew는 구현하지 않았다.
현재 장착 좌표 xyz=0·yaw=π와 차체/costmap 치수는 정밀 실측 보정 대상이다.
주기적 재정합은 정지 중 작은 오차를 교정하며, 모호한 지도에서는 보류한다.
큰 위치 오차는 관리자 화면의 수동 초기 위치 탐색으로 처리한다.
