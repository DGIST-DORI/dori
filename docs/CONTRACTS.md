# 실제 주행 인터페이스 계약

| 발행 → 수신 | 인터페이스 | 계약 |
|---|---|---|
| 사용자 → LLM | `/NAVIGATION_TEXT` String, `/NAVIGATION_MODE` Int32 | 텍스트를 먼저 전달. 0=중지, 1=처리 허용. 모드 변경 후 늦게 온 응답 폐기 |
| LLM → 이름 브리지 | `/named_goal` String | CSV의 정확한 이름 또는 cancel/list/reload. 임의 좌표·코드 실행 없음 |
| 이름 브리지 → Nav2 | `/navigate_to_pose` NavigateToPose | map, m, quaternion. 교체 시 이전 취소/종료 후 새 목표 전송 |
| 이름 브리지 → 구동 연결 | `/navigation/goal_active` Bool | 현재 승인된 목표만 구동 허용. 취소/거절/종료 즉시 false |
| Nav2 controller/behavior → smoother | `/nav/cmd_vel_raw` Twist | linear.x m/s, angular.z rad/s |
| smoother → 구동 연결 | `/nav/cmd_vel` Twist | SI, 0.3m/s·0.8rad/s 제한 |
| 구동 연결 → supervisor | `/auto/cmd_vel` Twist | x=v/1.72, z=w/7.0. 공통 비율 포화로 곡률 유지 |
| supervisor → drive controller | `/drive/cmd_vel` Twist | 정규화. AUTO에서 manual 입력은 무시, MANUAL에서 auto 입력은 무시 |
| drive controller → CAN bridge | `/bldc_mit_speed_cmd` MitCommand | ID 1=left, 2=right. v_des rad/s. (v∓w·간격/2)/반지름 |
| CAN → odom | `/joint_states` JointState | left/right_wheel_joint의 실측 position rad. 하드웨어 방향 보정 후 값 |
| CAN → odom/drive | `/dynamic_joint_states` DynamicJointState | 양 바퀴 feedback_age가 유한·0~0.2초. CAN 수신 시각에서 계산, cached position 재발행으로 갱신되지 않음 |
| odom → Nav2/매핑 | `/odom` Odometry | frame=odom, child=base_link, 위치 m, 속도 m/s·rad/s, 원본 JointState 시각 |
| C1 → Nav2/매핑 | `/scan` LaserScan | frame=laser, 실제 시각, 거리 m |

## TF와 시계

- `odom → base_link`: wheel_odometry_node 한 개만 발행. /odom과 동일한 측정 시각·pose.
- `map → odom`: 매핑은 Cartographer, 저장 지도 주행은 AMCL. 동시 사용 금지.
- `base_link → laser`: 실제 장착값의 static transform.
- 실기 use_sim_time=false. Isaac 전용 TF/restamp/odom_to_tf를 실기에 섞지 않음.
- AMCL transform_tolerance에 따른 미래 map TF 최대 1.1초를 허용. 센서 미래 시각 허용은 0.05초.

## 구동 차단

구동 연결은 모드·목표·실제 제어 상태·센서·TF·실제 드라이브 스케일을 함께 검사합니다. Nav 명령 0.25초, odom 0.25초, scan 0.5초 초과 시 구동을 차단합니다. `/navigation/drive_status`가 이유를 표시합니다. GetParameters로 드라이버 최대 속도 값과 변환 스케일을 확인하며 확인 결과도 만료됩니다.

`/navigation/halt`는 AUTO에서 drive controller를 즉시 정지시킵니다. 별도로 drive controller 자체에 0.3초 명령 watchdog 및 모터별 CAN 신선도 검사, system action 상태 검사가 있어 상위 프로세스 단절을 처리합니다. 이는 하드웨어 비상 정지 장치를 대체하지 않습니다.

시스템 모드: 0 MANUAL, 1 AUTO. action: 0 IDLE, 1 DRIVE, 2 TRANSFORM, 3 PAUSED, 4 ESTOP, 5 ERROR. 2 이상은 구동 금지. 비상 정지 해제는 기존 하드웨어 절차로만 수행하며 LLM/주행 시작이 해제하지 않습니다.

## 지도·목적지·LLM

CSV는 `name,x,y,yaw_deg,frame_id`이며 이름 중복/예약어/빈 목록, 비유한 좌표, map 이외 frame을 거부합니다. 지도 이미지·해상도·원점·점유 임계값 및 목적지 중심 셀을 검증합니다. 전체 로봇 외곽과 경로는 Nav2 costmap/planner가 판정합니다.

LLM은 등록된 이름만 선택합니다. 정확한 이름은 API를 우회합니다. Responses API의 출력 토큰 예산은 추론 토큰도 포함하므로 기본 1024로 두고 완료되지 않은 응답을 거부합니다([공식 API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create)). 외부 API 실제 인증/응답은 이번 오프라인 시험 범위 밖입니다.

## 검증 한계

소프트웨어 로봇은 CAN 물리 버스·모터 회전 방향·기어비·타이어 슬립·실제 장애물을 검증하지 않습니다. 반지름/간격/로봇 외곽/라이다 장착값은 실측 보정이 필요합니다. 기구 변형으로 바퀴 간격이나 지지 형상이 달라지면 해당 주행 자세의 값으로 다시 설정해야 합니다.

## 바퀴 방향 및 좌우 배정 수정 (2026-09-08 최종)

처음 양쪽 부호만 반전한 설정은 전후진을 바꾸면서 회전도 뒤집었습니다. 이후 사용자의 좌우 회전 반대 관찰을 반영하여 CAN 주소와 해당 모터의 방향 부호를 함께 교환했습니다.

- 논리 left_wheel_joint: CAN 2, direction_sign=+1
- 논리 right_wheel_joint: CAN 1, direction_sign=-1
- /bldc_mit_speed_cmd의 motor_id 1/2는 브리지의 논리 좌/우 선택 번호이며, 이제 물리 CAN 주소와 동일하지 않습니다. 실제 CAN 주소는 URDF에서 결정합니다.

직전 설정 대비 실제 CAN의 전진/후진 명령은 동일하며 회전 성분만 반전됩니다. encoder position/velocity/effort도 실제 주소에서 해당 논리 joint로 매핑하므로 odometry와 구동이 일치합니다. 라이다·조이스틱·Nav2에 추가 반전을 넣지 않습니다.

설치 launch의 URDF 문자열 평가와 좌우 ID/부호 및 명령·피드백 계산 검증 완료(`left_right_mapping_results.json`). 이는 실기 측정을 대신하지 않습니다. 전체 세션 재시작 후 짧게 실제 전진·좌회전을 확인해야 합니다. 방향이 잘못된 상태로 만든 지도는 새로 매핑하세요.
