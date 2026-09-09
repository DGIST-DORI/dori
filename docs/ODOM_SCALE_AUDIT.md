# Odometry 단위·배율 확인 — 2026-09-09

현재 소스와 설치 설정의 경로:

1. cubemars_hardware::parse_mit_feedback: MIT position 범위 [-4π,4π]를 rad로 디코딩하고 enc_off/direction_sign 적용. MIT 경로에는 위치/속도에 gear_ratio 적용이 없음. 이는 수신각이 출력축 각도라는 가정이며 실제 모터 펌웨어/매뉴얼 또는 바퀴 1회전으로 확인해야 함.
2. WheelOdometry::update: ds = 0.234 * (Δleft+Δright)/2, da = 0.234*(Δright−Δleft)/0.184. 반지름·간격은 m.
3. wheel_odometry_node: x/y를 /odom.pose.pose.position에 그대로 기록하고 동일 값으로 TF 발행. cm 배율 곱셈/나눗셈 없음.
4. Cartographer launch: /odom 직접 remap, 중간 거리 배율 변환 없음. Cartographer가 사용하는 길이는 m 기준.

실제 C++ 적분 클래스로 양쪽 각도 1회전(2π rad)을 입력한 결과 x=1.47026536188m, yaw=0. 이는 코드 단위 일관성 검사이며 물리 스케일 교정은 아님.

## 아직 확정하지 못한 항목

- 현재 wheel_radius=0.234는 반지름 23.4cm(지름 46.8cm)를 뜻함. 실제 지름이 23.4cm라면 반지름 0.117m이므로 기존 계산은 2배. 실제 반지름이 2.34cm라면 기존 계산은 10배.
- gear_ratio=10을 위치에 적용하지 않는 것이 맞는지는 수신 angle이 출력축인지 로터축인지에 달림. 출력축이면 추가 나눗셈은 오류. 로터축이면 출력축 각도 변환이 필요하며 명령·피드백·wrap·속도 한계를 일관되게 조정해야 함.
- MIT p_min/p_max도 실제 펌웨어의 프로토콜 범위와 일치해야 함. 설정값만으로 실제 범위를 증명할 수 없음.
- 바퀴 간격 0.184m가 틀리면 회전 배율에 영향.

## 필요한 실측

바퀴 실제 지름과 모터 모델/프로토콜 확인. 바퀴를 표시해서 실제 1회전할 때 /joint_states 각도 누적 변화가 2π인지 확인(직접 모터 명령 없이도 관찰 가능). 이후 바닥에서 알려진 직선 거리와 시작/끝 /odom 위치 차이를 비교한다. 이동 거리와 시간은 독립 실측이어야 하며 바퀴 명령 적분을 정답으로 삼지 않는다.

예: 실제 0.50m 이동에 /odom 변화가 50이면 100배, 5이면 10배, 1이면 2배 과대. 단일 시도에는 슬립이 섞일 수 있으므로 정/역방향으로 반복 확인.

이 확인 전에는 반지름이나 감속비를 추정으로 바꾸지 않았다. 앞선 공중 바퀴 시험에서 확인한 것은 엔코더 차분과 odom의 일치이며 실물 거리의 일치가 아니다.

Cartographer 입력 참고: https://docs.ros.org/en/melodic/api/cartographer_ros/html/sensor__bridge_8cc_source.html
