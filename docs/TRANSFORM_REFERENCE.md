# 고정 기준각 변신

수정 대상은 `/home/dori/robot_ws`이다. 바탕화면 실행 스크립트도 이 작업공간을 사용한다.

## 기준각과 단계

`src/robot_transform/config/transform_params.yaml`에서 설정한다. 아래 기준각은 **JointState 피드백과 같은 모터축 도(deg)** 단위다. 기구각과 혼용하지 않는다.

| 파라미터 | 의미 | 기존 보정값 |
|---|---|---:|
| `left_bldc_alignment_offset_deg` | 모터 1의 A 준비 기준각 | 36.51 |
| `right_bldc_alignment_offset_deg` | 모터 2의 A 준비 기준각 | -43.1659 |
| `motor3_grid_offset_deg` | 모터 3의 A 준비 기준각. 호환성을 위해 기존 이름 유지 | -6.77 |
| `motor4_a_reference_deg` | 모터 4의 A 준비 기준각 | 8.88 |
| `pose_a_reference_deg` | motor_4_joint의 A 판정각 | 8.88 |
| `pose_b_reference_deg` | motor_4_joint의 B 판정각 | 188.88 |
| `left_bldc_motor_per_mechanical` | 기구 1°당 BLDC 피드백 각도 | 2.0 |
| `right_bldc_motor_per_mechanical` | 기구 1°당 BLDC 피드백 각도 | 2.0 |

현재 BLDC MIT 피드백은 하드웨어 계층에서 `direction_sign`이 적용된다. 이 설정은 외부 기구의 1:2 비율이며, URDF의 모터 내부 `gear_ratio=10`과 구분한다. 시퀀스는 기구 기준 90°로 작성하고 BLDC 명령 생성 시 180°로 변환한다. DXL은 기존 기구비 1:1을 유지한다. `18→108→198`은 양의 회전 예시이고, 실제 변신 순서의 기존 방향(모터 3·4 음의 방향 등)은 유지한다.

기준값은 YAML에 고정되며 매 변신마다 측정값으로 덮어쓰지 않는다. 현재 위치는 동일한 기구 위상의 회전수 선택에만 사용한다(기준각 + 정수×기구 한 바퀴). 106°에 도착한 뒤 다음 목표가 196°로 밀리는 오차 누적은 일어나지 않는다. 전원을 껐다 켜서 엔코더 회전수가 초기화돼도 고정된 물리 위상에서 시작한다. 전체 누적 회전 횟수를 영구 저장하는 기능은 아니다.

B 준비 위치는 고정 A 기준과 A→B 시퀀스의 누적량으로 계산한다. 현재 시퀀스의 모터축 총량은 `[+360, -360, -450, -540]°`다. B에서 A 기준으로 먼저 복귀하지 않는다. A/B 판정각과 시퀀스 종점이 일치하지 않으면 준비 명령을 보내기 전에 거부한다.

준비는 모터 1→2→3→4 순서로 진행하고, 각 준비 목표 도달·정지 확인 후 변신 단계로 넘어간다. DXL 준비 보정량이 `max_dxl_preparation_deg`(기본 45°)를 넘으면 거부한다. 이는 중간 변신 자세를 정상 시작 자세로 오인하여 큰 복귀 동작을 하는 것을 막는다. 정상 자세의 작은 정렬 보정용이며, 중간 실패 상태를 자동 복구하는 시퀀스가 아니다.

원래 14단계의 마지막 DXL -180°를 -90° 두 단계로 나누었다. 따라서 준비 4단계 + 변신 15단계다. 각 90° 단계에는 도달·정지 확인이 있다. 허용 오차는 제어기 YAML의 기존 값(BLDC 모터축 4°, DXL 2°)을 유지한다. 정확도나 부하 유지 능력의 실측 검증은 별도다.

## DXL 경로

물리 ID 1·2(논리 motor_3_joint·motor_4_joint)는 2026-09-09 읽기 전용 실측에서 XH540-V270-R(모델 번호 1140)로 확인됐다. 이전 소스 주석의 모델 기록은 잘못돼 있었다. 드라이버는 모델을 읽고 확인한 후 다회전 위치 모드 4를 설정·재확인한다. 물리 ID 3은 기존 단회전 모드 3을 유지한다. 초기화 실패 시 토크 해제 명령 후 종료한다. 모드 전환 전에 모션 프로파일을 읽어 복구하고, 현재 위치를 초기 목표로 설정한 뒤 토크를 켠다.

명령과 피드백은 4096 count/rev로 변환한다. ID 1·2는 음수와 360° 이상의 연속 목표를 전달하며, 제어기는 `목표 - 실제`로 오차를 계산한다. `18→-72`를 `18→288`로 바꾸지 않는다. 다회전 목표 범위 ±1,048,575 count를 검사한다. ID 3은 0~4095 count를 유지한다. 기존 4095 count/rev 변환에서 생기던 스케일 오차가 수정되었으므로 실제 기준각을 다시 측정할 때 새 피드백 값을 사용한다.

공식 근거: [ROBOTIS XH540-V270-R](https://emanual.robotis.com/docs/en/dxl/x/xh540-v270/#operating-mode11). 다회전 모드에서는 하드웨어 단회전 Min/Max Position Limit이 적용되지 않으므로 기구 제한은 별도로 고려해야 한다.

## 피드백과 정지

DXL ID 1·2·3을 순환 조회한다. 새로 읽은 위치만 발행하고 속도는 연속 두 샘플의 차분으로 계산한다. 실패한 ID의 캐시를 새 시간으로 재발행하지 않는다. 다른 정상 ID는 계속 읽는다.

관리자와 제어기는 메시지 시각, 위치/속도 유효성, `feedback_timeout_sec`(0.5초)를 검사한다. 피드백이 없거나 만료되면 시작을 거부하거나 실행 중 단계를 실패 처리한다. BLDC는 속도·피드포워드를 0으로 보내고, DXL은 `/dxl_stop_cmd`(논리 ID) → 브리지 `/stop_position`(물리 ID, SetPosition.position은 미사용) → 버스에서 현재 위치를 직접 읽어 정지 목표로 설정한다. 읽기/쓰기 실패 시 해당 ID에 토크 해제 명령을 보낸다. 통신선 자체가 끊기면 소프트웨어 정지 명령 전달을 보장할 수 없다.

일시정지는 실행 중 단계를 정지시키며, 재개는 같은 저장 목표를 사용한다. 일시정지 중 도착한 단계 결과도 보존하여 단계를 중복 발행하지 않는다. 최종 성공은 최신 motor_4_joint가 요청 A/B 판정각에 들어왔을 때만 발행한다. `force_initial_pose`로 실제 피드백 검사를 우회하는 기능은 제거했다.

## 소프트웨어 검증

```bash
./scripts/build.sh --packages-up-to robot_transform dynamixel_sdk_examples
g++ -std=c++17 -Wall -Wextra -Werror -I src/robot_transform/include \
  tests/test_transform_plan.cpp -o /tmp/test_transform_plan
/tmp/test_transform_plan
source /opt/ros/humble/setup.bash
source install/setup.bash
ROS_DOMAIN_ID=93 ROS_LOCALHOST_ONLY=1 python3 tests/integration_transform.py
```

통합 테스트는 관리자·제어기·DXL 브리지·DXL 피드백 노드와 가짜 서비스만 실행한다. 하드웨어 드라이버, CAN, 시리얼 장치는 실행하지 않는다.

2026-09-09 검증 결과:

- 관련 5개 패키지 빌드 성공.
- C++ 목표 계산 테스트: A/B 100회 반복, 도착 오차 비누적, 기구 90° 단위, 0° 경계, 재시작 위상 선택, 잘못된 입력 검사 통과.
- 격리 ROS 통합 테스트: 관리자 A↔B 4회 변신, 일시정지 중 결과 처리, 피드백 누락 거부, 최종 motor_4_joint 판정 통과.
- 제어기: 연속 회전수 불일치 차단, 일시정지 전후 명령 경합, 같은 목표 재개, BLDC/DXL 피드백 만료 정지, DXL timeout 정지 통과.
- DXL 입출력: ID 1·2·3 피드백, 음수 count 변환, 실패 ID의 캐시 발행 차단, 범위/NaN 거부, 정지 ID 매핑 통과.
- YAML 파싱 및 중복 키 검사 통과.
- 하드웨어 드라이버는 빌드만 수행했다. 실제 모델 조회·모드 변경·기구 구동은 수행하지 않았다.

수정 전 주요 소스 백업: `backups/transform_fixed_reference_20260909_184856/`.
