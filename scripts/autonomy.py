"""Start or attach to the Dori autonomous stack without a gamepad dependency."""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request
from urllib.parse import urlsplit

from scripts.robot_stack import ROOT, stop_children, wait_for_base
from navigation_contract import validate_map

GROUPS = {
    'control': {'controller_manager','drive_controller_node','mode_manager_node',
                'imu_node','body_pitch_node','servo3_pitch_follower_node'},
    'lidar': {'sllidar_node'},
    'odometry': {'lidar_odometry'},
    'navigation': {'map_server','amcl','controller_server','planner_server',
                   'behavior_server','bt_navigator','velocity_smoother','named_goal_bridge','nav_drive_bridge'},
}


def component_plan(names):
    counts=Counter(names);names=set(names)
    conflict=names & {'cartographer_node','lidar_imu_odometry','wheel_odometry_node'}
    if conflict:raise RuntimeError('다른 매핑/오도메트리 세션을 먼저 종료하세요: '+', '.join(sorted(conflict)))
    result={}
    for label,required in GROUPS.items():
        present=required & names
        if any(counts[name]>1 for name in required):raise RuntimeError(label+': 중복 노드가 있습니다')
        if present and present!=required:
            raise RuntimeError(label+': 일부 노드만 실행 중입니다. 기존 실행기를 확인하세요: '+', '.join(sorted(required-present)))
        result[label]='reuse' if present else 'start'
    if result['odometry']=='start' and 'base_to_laser_tf' in names:
        raise RuntimeError('기존 base_to_laser_tf를 종료한 뒤 다시 실행하세요. 중복 TF를 만들지 않습니다.')
    return result


def viewer_ready(port,role):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/session',timeout=1) as response:
            return json.load(response).get('role')==role
    except (OSError,ValueError):return False


def joystick_processes():
    found=[]
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args=(proc/'cmdline').read_bytes().split(b'\0')
            names={Path(arg.decode(errors='replace')).name for arg in args[:2]}
            if names & {'joystick_input_node','joy_node'} and proc.stat().st_uid==os.getuid():
                found.append((int(proc.name),'joystick_input_node' in names))
        except (OSError,ValueError):pass
    return sorted(found,key=lambda item:not item[1])  # Stop watchdog before device driver.


def main():
    parser=argparse.ArgumentParser(description='게임패드 없이 Dori 자율주행과 웹 화면을 한 번에 준비합니다.')
    parser.add_argument('--map',type=Path,default=ROOT/'maps/live_navigation_20261023_1938.yaml')
    parser.add_argument('--check',action='store_true',help='실행 계획과 기존 상태만 확인; 노드/장치 변경 없음')
    args=parser.parse_args();args.map=args.map.resolve();validate_map(str(args.map),None)
    lock=open(Path(os.getenv('XDG_RUNTIME_DIR','/tmp'))/f'dori-autonomy-{os.getuid()}.lock','w')
    try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('자율주행 통합 스크립트가 이미 실행 중입니다.')

    import rclpy
    from rcl_interfaces.srv import GetParameters
    from lifecycle_msgs.srv import GetState,ChangeState
    from std_msgs.msg import Int32
    from geometry_msgs.msg import Twist
    rclpy.init();node=rclpy.create_node('autonomy_session')
    children=[];handles=[];started=False
    mode=node.create_publisher(Int32,'/NAVIGATION_MODE',10)
    manual=node.create_publisher(Twist,'/manual/cmd_vel',10)

    def call(client,request,timeout=3.):
        if not client.wait_for_service(timeout_sec=timeout):return None
        future=client.call_async(request);rclpy.spin_until_future_complete(node,future,timeout_sec=timeout)
        if future.done():return future.result()
        client.remove_pending_request(future);return None

    def parameter(target,name):
        client=node.create_client(GetParameters,target+'/get_parameters')
        try:
            for _ in range(3):
                result=call(client,GetParameters.Request(names=[name]))
                if result and result.values:return result.values[0].string_value
            raise RuntimeError(target+' 파라미터 확인 실패')
        finally:node.destroy_client(client)

    def stop_motion():
        for _ in range(3):
            mode.publish(Int32(data=0));manual.publish(Twist());rclpy.spin_once(node,timeout_sec=.1)

    def start(label,command):
        log=(logs/(label+'.log')).open('w');handles.append(log)
        proc=subprocess.Popen(command,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,
            env=env,start_new_session=True,cwd=ROOT)
        children.append((label,proc));print(f'{label}: 시작 PID {proc.pid}',flush=True)

    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:rclpy.spin_once(node,timeout_sec=.1)
        deadline=time.monotonic()+12
        while True:
            names=[name for name,_ in node.get_node_names_and_namespaces()]
            try:plan=component_plan(names);break
            except RuntimeError:
                if time.monotonic()>deadline:raise
                rclpy.spin_once(node,timeout_sec=.5)
        if plan['navigation']=='reuse':
            if Path(parameter('/map_server','yaml_filename')).resolve()!=args.map:raise RuntimeError('실행 중인 지도와 --map이 다릅니다. 기존 주행 실행기를 종료하세요.')
            if parameter('/named_goal_bridge','goal_source')!='web':raise RuntimeError('기존 주행이 web 목표 모드가 아닙니다.')
        admin=viewer_ready(8080,'admin');public=viewer_ready(7070,'user')
        if admin!=public:raise RuntimeError('8080/7070 중 일부만 실행 중입니다. 기존 뷰어를 확인하세요.')
        plan['web']='reuse' if admin else 'start'
        gamepads=joystick_processes()
        https_file=Path.home()/'.config/dori/user_https_url'
        https_url=https_file.read_text().strip() if https_file.exists() else ''
        serve_ok=False
        if https_url:
            host=urlsplit(https_url).netloc
            result=subprocess.run(['tailscale','serve','status','--json'],capture_output=True,text=True,check=True)
            config=json.loads(result.stdout)
            serve_ok=(config.get('TCP',{}).get('7070',{}).get('HTTPS') is True and
                config.get('Web',{}).get(host,{}).get('Handlers',{}).get('/',{}).get('Proxy')=='http://127.0.0.1:7070')
        print(json.dumps({'map':str(args.map),'components':plan,'joystick_input_on_start':'disabled',
            'existing_gamepad_nodes_to_stop':[pid for pid,_ in gamepads],'https_ready':serve_ok},ensure_ascii=False,indent=2),flush=True)
        if args.check:return
        if https_url and not serve_ok:
            subprocess.run(['sudo','tailscale','serve','--bg','--https=7070','http://127.0.0.1:7070'],check=True)
        started=True;stop_motion()
        # Reusing a manually started stack must not retain its gamepad watchdog.
        for pid,_ in gamepads:
            try:os.kill(pid,signal.SIGINT)
            except ProcessLookupError:continue
        deadline=time.monotonic()+5
        while joystick_processes() and time.monotonic()<deadline:time.sleep(.1)
        if joystick_processes():raise RuntimeError('기존 조이스틱 입력이 종료되지 않았습니다. 해당 실행기를 확인하세요.')
        control=[str(ROOT/'scripts/run_robot_control.sh'),'--no-joystick']
        if plan['control']=='start':subprocess.run(control+['--prepare-only'],check=True)
        env=os.environ.copy();env.update(ROBOT_USE_WHEEL_ODOMETRY='false',ROBOT_ODOM_PUBLISH_TF='false')
        logs=ROOT/'log'/('autonomy_'+time.strftime('%Y%m%d_%H%M%S'));logs.mkdir(parents=True)
        (logs/'session.json').write_text(json.dumps({'map':str(args.map),'plan':plan},indent=2))
        if plan['control']=='start':start('control',control)
        if plan['lidar']=='start':start('lidar',[str(ROOT/'scripts/run_lidar.sh')])
        if plan['odometry']=='start':start('odometry',['ros2','launch','robot_mapping','lidar_odometry.launch.py'])
        if plan['web']=='start':start('web',[str(ROOT/'scripts/start_web_viewer.sh'),'--mode','auto'])
        print('관리자: http://<robot-ip>:8080\n사용자: '+(https_url or 'http://<robot-ip>:7070'),flush=True)
        wait_for_base(children,env,logs)
        if plan['navigation']=='start':start('navigation',[str(ROOT/'scripts/run_navigation.sh'),
            'map:='+str(args.map),'goal_source:=web','publish_laser_tf:=false'])
        # Recover an inactive AMCL when a startup service reply was lost. Never
        # reconfigure an active node or reset the user's map position.
        state_client=node.create_client(GetState,'/amcl/get_state')
        activate=node.create_client(ChangeState,'/amcl/change_state');inactive_since=None
        deadline=time.monotonic()+60
        while time.monotonic()<deadline:
            result=call(state_client,GetState.Request(),2.)
            if result and result.current_state.id==3:break
            if result and result.current_state.id==2:
                if inactive_since is None:inactive_since=time.monotonic()
                if time.monotonic()-inactive_since>3:
                    request=ChangeState.Request();request.transition.id=3;call(activate,request)
            time.sleep(.3)
        else:raise RuntimeError('AMCL 활성화를 확인하지 못했습니다. '+str(logs))
        print('준비 완료. 8080에서 현재 위치를 확인/적용한 뒤 목표를 지정하세요.\nCtrl+C: AUTO 정지 후 이 스크립트가 시작한 노드 종료.\n로그: '+str(logs),flush=True)
        while True:
            rclpy.spin_once(node,timeout_sec=.2)
            for label,proc in children:
                if proc.poll() is not None:raise RuntimeError(f'{label} 종료됨. 로그: {logs}')
    except KeyboardInterrupt:pass
    finally:
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        if started and rclpy.ok():stop_motion()
        stop_children(children)
        for log in handles:log.close()
        node.destroy_node();rclpy.shutdown();lock.close()


def interrupted(_signum,_frame):
    raise KeyboardInterrupt


if __name__=='__main__':
    signal.signal(signal.SIGTERM,interrupted)
    main()
