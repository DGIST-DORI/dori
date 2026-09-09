#!/usr/bin/env bash
# 통합 실기 제어 실행: BLDC, Dynamixel, supervisor, 변형 제어, IMU, 조이스틱.
# 기존 launch 파일의 파라미터/제한값을 사용한다.
# 실행하면 모터 토크 및 서보 자동 추종이 활성화될 수 있다.
# Ctrl+C 종료 시 기존 Dynamixel 드라이버는 서보 토크를 해제한다.
# CANable2 연결 및 게임패드 xpad 연결을 자동 준비한다.

set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_CONTROL_WS="${ROBOT_CONTROL_WS:-$(cd "$SCRIPT_DIR/.." && pwd)}"
ROBOT_CONTROL_JOYSTICK=true
ROBOT_CONTROL_CHECK_ONLY=false
ROBOT_CONTROL_PREPARE_ONLY=false

usage() {
    cat <<'HELP'
사용법:
  ./run_robot_control.sh                 전체 실기 제어 실행 (조이스틱 포함)
  ./run_robot_control.sh --no-joystick   조이스틱 없이 실행
  ./run_robot_control.sh --prepare-only  하드웨어 준비만 수행
  ./run_robot_control.sh --check         실행 전 조건만 검사, 노드 실행 안 함
  ./run_robot_control.sh --help          도움말

이 파일 하나에 CAN·게임패드 준비 코드가 포함되어 있습니다.
CANable2를 찾아 can1을 연결하고 게임패드 xpad 드라이버를 자동 연결합니다.
CAN을 먼저 준비합니다. 다른 장치 준비가 실패해도 이미 켠 can1은 유지됩니다.
서보·IMU·게임패드 준비가 끝나야 전체 제어 노드를 시작합니다.
이번에 검증한 SDL classic(js 장치) 모드로 실제 /joy를 반복 발행합니다.
필요한 경우 sudo 비밀번호를 요청합니다. 스크립트 자체는 일반 사용자로 실행하세요.
이미 실행 중인 제어 노드가 있으면 중복 실행을 거부합니다.
USB 장치 연결 및 작업공간 빌드는 미리 완료해야 합니다.
--check는 상태만 검사하며 sudo나 장치 변경을 수행하지 않습니다.
--check 통과는 실제 센서/조이스틱 데이터 갱신이나 기구 안전을 보증하지 않습니다.
HELP
}

for argument in "$@"; do
    case "$argument" in
        --no-joystick) ROBOT_CONTROL_JOYSTICK=false ;;
        --check) ROBOT_CONTROL_CHECK_ONLY=true ;;
        --prepare-only) ROBOT_CONTROL_PREPARE_ONLY=true ;;
        --help|-h) usage; exit 0 ;;
        *) printf '알 수 없는 옵션: %s\n' "$argument" >&2; usage; exit 2 ;;
    esac
done

fail() { printf '실행 중단: %s\n' "$*" >&2; exit 1; }

[[ $EUID -ne 0 ]] || fail 'sudo 없이 일반 사용자로 실행해 주세요.'
[[ -f /opt/ros/humble/setup.bash ]] || fail 'ROS 2 Humble 설치를 찾을 수 없습니다.'
[[ -f "$ROBOT_CONTROL_WS/install/setup.bash" ]] || fail '작업공간 install/setup.bash가 없습니다.'

# ROS setup 스크립트의 미정의 환경변수 사용 때문에 nounset은 사용하지 않는다.
unset AMENT_PREFIX_PATH COLCON_PREFIX_PATH CMAKE_PREFIX_PATH PYTHONPATH LD_LIBRARY_PATH
source /opt/ros/humble/setup.bash
source "$ROBOT_CONTROL_WS/install/setup.bash"
export ROBOT_CONTROL_JOYSTICK

# 준비 단계부터 잠가 두 실행이 동시에 CAN/입력 장치를 변경하지 않게 한다.
command -v flock >/dev/null || fail 'flock 명령이 필요합니다.'
exec 9>"${XDG_RUNTIME_DIR:-/tmp}/robot-control-${UID}.lock"
flock -n 9 || fail '통합 실행 스크립트가 이미 실행 중입니다.'

# 기존 제어 노드가 있으면 하드웨어 변경 전 중단한다.
hardware_args=()
[[ "$ROBOT_CONTROL_CHECK_ONLY" == true ]] && hardware_args+=(--check)
[[ "$ROBOT_CONTROL_JOYSTICK" == false ]] && hardware_args+=(--no-joystick)
/usr/bin/python3 - "${hardware_args[@]}" <<'PY'
import os
from pathlib import Path
import serial  # 누락 시 하드웨어 노드 실행 전에 실패

blocked = {
    'ros2_control_node', 'read_write_node', 'bldc_command_bridge_node',
    'drive_controller_node', 'wheel_torque_controller_node',
    'dxl_bridge_node', 'dxl_state_publisher_node',
    'mode_manager_node', 'transform_manager_node', 'transform_controller_node',
    'error_manager_node', 'joy_node', 'joystick_input_node',
    'keyboard_input_node', 'virtual_vlm_input_node', 'wheel_odometry_node',
    'imu_node', 'body_pitch_node', 'body_stabilizer_node', 'servo3_pitch_follower_node',
}
running = []
for proc in Path('/proc').glob('[0-9]*'):
    try:
        args = (proc / 'cmdline').read_bytes().split(b'\0')
    except (FileNotFoundError, PermissionError, ProcessLookupError):
        continue
    names = {Path(arg.decode(errors='replace')).name for arg in args[:2]}
    if names & blocked:
        running.append(f"PID {proc.name}: {', '.join(sorted(names & blocked))}")
if running:
    raise SystemExit('기존 제어 노드가 실행 중입니다. 중복 실행하지 않습니다.\n' + '\n'.join(running))

#!/usr/bin/python3
"""Prepare the existing robot hardware; never issue motor commands."""
XPAD_RECOVERY_CODE = '#!/usr/bin/python3\n"""Bind only the 2dc8:310b vendor interface to xpad, with robot input stopped.\n\nUsage: sudo python3 fix_gamepad.py\nThis is a temporary binding (until reboot/module unload), not a firmware change.\n"""\nimport os\nfrom pathlib import Path\nimport subprocess\nimport sys\nimport time\n\n\ndef main():\n    if os.geteuid() != 0:\n        sys.exit(\'관리자 권한 필요: sudo python3 \' + str(Path(__file__).resolve()))\n    # Binding can immediately resume joystick commands. Refuse live input.\n    for proc in Path(\'/proc\').glob(\'[0-9]*\'):\n        try:\n            args = (proc / \'cmdline\').read_bytes().split(b\'\\0\')\n        except (FileNotFoundError, PermissionError):\n            continue\n        if any(Path(a.decode(errors=\'replace\')).name in\n               {\'joy_node\', \'joystick_input_node\'} for a in args[:2]):\n            sys.exit(\'조이스틱 입력 노드가 실행 중입니다. 입력 노드를 먼저 종료해야 합니다.\')\n    interfaces = []\n    for device in Path(\'/sys/bus/usb/devices\').glob(\'*\'):\n        try:\n            if ((device / \'idVendor\').read_text().strip() == \'2dc8\' and\n                    (device / \'idProduct\').read_text().strip() == \'310b\'):\n                for interface in device.glob(device.name + \':*\'):\n                    if (interface / \'bInterfaceClass\').read_text().strip() == \'ff\':\n                        interfaces.append(interface)\n        except FileNotFoundError:\n            continue\n    if len(interfaces) != 1:\n        sys.exit(\'대상 게임패드 인터페이스가 정확히 하나가 아닙니다. 변경하지 않았습니다.\')\n    interface = interfaces[0]\n    if (interface / \'driver\').exists():\n        if (interface / \'driver\').resolve().name == \'xpad\':\n            print(\'이미 xpad에 연결되어 있습니다.\')\n            return\n        sys.exit(\'다른 드라이버가 연결되어 있습니다. 변경하지 않았습니다.\')\n    subprocess.run([\'/sbin/modprobe\', \'xpad\'], check=True)\n    # ff restricts the dynamic ID to the gamepad\'s vendor-specific interface.\n    Path(\'/sys/bus/usb/drivers/xpad/new_id\').write_text(\'2dc8 310b ff\\n\')\n    subprocess.run([\'/bin/udevadm\', \'settle\', \'--timeout=5\'], check=True)\n    time.sleep(1)\n    if (interface / \'driver\').resolve().name != \'xpad\':\n        sys.exit(\'xpad 연결을 확인하지 못했습니다. 추가 진단이 필요합니다.\')\n    print(\'xpad 연결 완료. 로봇 입력을 재개하기 전에 별도 /diagnostics/joy에서 축과 버튼을 검증하세요.\')\n\n\nif __name__ == \'__main__\':\n    main()\n'

import argparse
import os
from pathlib import Path
import subprocess
import time


def can_up():
    path = Path('/sys/class/net/can1/flags')
    return path.exists() and bool(int(path.read_text().strip(), 16) & 1)


def gamepads():
    return [p for p in Path('/dev/input/by-id').glob('*8BitDo*-joystick')
            if '-event-joystick' not in p.name]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--no-joystick', action='store_true')
    args = parser.parse_args()
    errors = []
    for device, label in [
        ('/dev/serial/by-id/usb-FTDI_USB__-__Serial_Converter_FTAU591Z-if00-port0', 'Dynamixel USB'),
        ('/dev/serial/by-id/usb-Arduino_Nano_33_BLE_B9CD51D670B512DB-if00', 'IMU'),
    ]:
        if not Path(device).exists():
            errors.append(f'{label}: {device} 없음. USB 연결과 전원을 확인하세요.')
        elif not os.access(device, os.R_OK | os.W_OK):
            errors.append(f'{label}: {device} 읽기/쓰기 권한 없음 (dialout 그룹 확인).')

    needs_can = not can_up()
    can_errors = []
    adapters = list(Path('/dev/serial/by-id').glob('*CANable2*-if00'))
    if needs_can and not Path('/sys/class/net/can1').exists() and len(adapters) != 1:
        can_errors.append('CANable2 USB 어댑터를 정확히 하나 찾을 수 없습니다. DFU 모드와 USB 연결을 확인하세요.')
    needs_pad = not args.no_joystick and len(gamepads()) != 1
    if not args.no_joystick and len(gamepads()) > 1:
        errors.append('게임패드가 여러 개입니다. 사용할 게임패드 하나만 연결하세요.')
    needs_access = (not args.no_joystick and len(gamepads()) == 1
                    and not os.access(gamepads()[0], os.R_OK))

    print(f'CAN can1: {"UP" if not needs_can else "준비 필요"}', flush=True)
    if not args.no_joystick:
        print(f'게임패드: {"연결됨" if not needs_pad else "xpad 연결 필요"}', flush=True)
    if needs_pad:
        ids = []
        for usb in Path('/sys/bus/usb/devices').glob('*'):
            try:
                ids.append(((usb / 'idVendor').read_text().strip(),
                            (usb / 'idProduct').read_text().strip()))
            except FileNotFoundError:
                pass
        if ('2dc8', '310b') not in ids:
            errors.append('8BitDo PC 모드(2dc8:310b)를 찾지 못했습니다. 연결·모드를 확인하세요.')
    if args.check:
        if can_errors or errors:
            raise SystemExit('\n'.join(can_errors + errors))
        if needs_can or needs_pad or needs_access:
            raise SystemExit('자동 준비가 필요합니다. --check 없이 실행하세요.')
        print('실행 전 조건 검사 완료.')
        return
    if can_errors:
        raise SystemExit('\n'.join(can_errors))
    if needs_can or ((needs_pad or needs_access) and not errors):
        print('CAN/게임패드 준비에 관리자 권한을 사용합니다. 요청되면 sudo 비밀번호를 입력하세요.', flush=True)
        subprocess.run(['sudo', '-v'], check=True)
    if needs_can:
        if not Path('/sys/class/net/can1').exists():
            # Use the USB identity, not an unstable ttyACM number.
            adapter = str(adapters[0].resolve())
            for proc in Path('/proc').glob('[0-9]*'):
                try:
                    command = (proc / 'cmdline').read_bytes().split(b'\0')
                except (FileNotFoundError, PermissionError, ProcessLookupError):
                    continue
                if command and Path(command[0].decode(errors='replace')).name == 'slcand':
                    if any(Path(a.decode(errors='replace')).resolve() == Path(adapter)
                           for a in command[1:] if a.startswith(b'/dev/')):
                        raise SystemExit('이 CAN 어댑터의 slcand가 이미 실행 중이지만 can1이 없습니다. 기존 연결을 확인하세요.')
            subprocess.run(['sudo', 'slcand', '-o', '-s8', '-t', 'hw', '-S', '3000000', adapter, 'can1'], check=True)
            for _ in range(30):
                if Path('/sys/class/net/can1').exists():
                    break
                time.sleep(0.1)
        subprocess.run(['sudo', 'ip', 'link', 'set', 'can1', 'up'], check=True)
        if not can_up():
            raise SystemExit('CAN can1 활성화 실패.')
    print('CAN can1: UP 확인 완료.', flush=True)
    if errors:
        raise SystemExit('CAN 준비는 완료했습니다. 아래 장치를 준비한 뒤 같은 명령으로 다시 실행하세요.\n'
                         + '\n'.join(errors) + '\n전체 제어 노드는 시작하지 않았습니다.')
    if needs_pad:
        subprocess.run(['sudo', '/usr/bin/python3', '-c', XPAD_RECOVERY_CODE], check=True)
        for _ in range(30):
            if len(gamepads()) == 1:
                break
            time.sleep(0.1)
        if len(gamepads()) != 1:
            raise SystemExit('게임패드 연결 확인 실패.')
    if not args.no_joystick and not os.access(gamepads()[0], os.R_OK):
        # Grant read access only to the selected classic joystick device.
        subprocess.run(['sudo', 'setfacl', '-m', f'u:{os.getuid()}:r',
                        str(gamepads()[0].resolve())], check=True)
        if not os.access(gamepads()[0], os.R_OK):
            raise SystemExit('게임패드 읽기 권한 설정 실패.')
    if not args.no_joystick:
        print(f'조이스틱 입력: {gamepads()[0].resolve()} (SDL classic, 반복 발행 20 Hz 기본값)', flush=True)
    print('CAN·시리얼·게임패드 준비 완료.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f'하드웨어 준비 명령 실패 (exit {exc.returncode}). 노드를 시작하지 않았습니다.')

PY

if [[ "$ROBOT_CONTROL_CHECK_ONLY" == true || "$ROBOT_CONTROL_PREPARE_ONLY" == true ]]; then
    exit 0
fi

# Same SDL backend used in the successful /joy recovery. No fake messages.
export SDL_LINUX_JOYSTICK_CLASSIC=1
export SDL_JOYSTICK_HIDAPI=0
if [[ "$ROBOT_CONTROL_JOYSTICK" == true ]]; then
    shopt -s nullglob
    for joystick in /dev/input/by-id/*8BitDo*-joystick; do
        [[ "$joystick" == *-event-joystick ]] && continue
        export SDL_JOYSTICK_DEVICE="$joystick"
    done
fi
cd "$ROBOT_CONTROL_WS"
printf '전체 제어 시작 (조이스틱: %s). 종료: Ctrl+C\n' "$ROBOT_CONTROL_JOYSTICK"
# 하위 노드를 따로 중복 실행하지 않고 기존 통합 launch가 수명주기를 관리한다.
exec ros2 launch robot_bringup system_real_with_imu.launch.py \
    "use_joystick:=$ROBOT_CONTROL_JOYSTICK" \
    "odom_publish_tf:=${ROBOT_ODOM_PUBLISH_TF:-true}" \
    "odom_scale:=${ROBOT_ODOM_SCALE:-1.0}"
