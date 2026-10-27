#!/usr/bin/env python3
"""Own the lifetime of one hardware + mapping/navigation session."""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'ros2_ws/src/robot_navigation/scripts'))
from navigation_contract import validate_map



def stop_children(children, grace=8.0, residual_grace=3.0):
    """Stop only sessions created here, including descendants of an exited launcher."""
    def group_alive(p):
        try: os.killpg(p.pid, 0); return True
        except ProcessLookupError: return False
    def group_signal(p, sig):
        try: os.killpg(p.pid, sig)
        except ProcessLookupError: pass
    for _, p in reversed(children):
        if p.poll() is None:
            try: p.send_signal(signal.SIGINT)
            except ProcessLookupError: pass
    deadline=time.monotonic()+grace
    for _, p in children:
        try: p.wait(timeout=max(0,deadline-time.monotonic()))
        except subprocess.TimeoutExpired: pass
    # A launcher can exit while its ROS children are still alive in its process group.
    # Do not use parent poll()/wait() as proof that the entire session has stopped.
    for sig in (signal.SIGINT, signal.SIGTERM):
        remaining=[p for _,p in children if group_alive(p)]
        if not remaining: break
        for p in remaining: group_signal(p,sig)
        deadline=time.monotonic()+residual_grace
        while time.monotonic()<deadline:
            for p in remaining: p.poll()
            if not any(group_alive(p) for p in remaining): break
            time.sleep(0.05)
    for _, p in children:
        if group_alive(p): group_signal(p,signal.SIGKILL)
        try: p.wait(timeout=1)
        except subprocess.TimeoutExpired: pass


def wait_for_base(children, env, logs, timeout=60.0):
    """Bounded startup retries; an initializing controller is not a dead CAN link yet."""
    deadline=time.monotonic()+timeout
    attempt=0
    while time.monotonic()<deadline:
        for label,p in children:
            if p.poll() is not None:
                raise RuntimeError(f'{label} exited ({p.returncode}); inspect {logs / (label+".log")}')
        attempt+=1
        try:
            result=subprocess.run([sys.executable,str(ROOT/'scripts/preflight.py'),'--stage','base','--duration','5'],
                capture_output=True,text=True,env=env,timeout=min(30,max(.1,deadline-time.monotonic())))
        except subprocess.TimeoutExpired:
            print('Controller/sensor discovery still pending...',flush=True)
            continue
        (logs/f'base_check_{attempt}.log').write_text(result.stdout+result.stderr)
        if result.returncode==0:
            print(result.stdout,flush=True)
            return
        try: errors=json.loads(result.stdout)['errors']
        except (ValueError,KeyError): errors=[result.stderr[-500:] or 'Preflight failed; see session logs']
        print('Waiting for base readiness: '+'; '.join(errors),flush=True)
    raise RuntimeError(f'Base did not become ready within {timeout:.0f}s; inspect {logs}. Mapping was not started.')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('mode',choices=['mapping','navigation'])
    parser.add_argument('--map')
    parser.add_argument('--goal-source',choices=['rviz','web'],default='web')
    parser.add_argument('--no-joystick',action='store_true')
    parser.add_argument('--rviz',action='store_true')
    parser.add_argument('--no-web',action='store_true')
    parser.add_argument('--web-port',type=int,default=8080)
    parser.add_argument('--laser-x',type=float,default=0)
    parser.add_argument('--laser-y',type=float,default=0)
    parser.add_argument('--laser-z',type=float,default=0)
    parser.add_argument('--laser-roll',type=float,default=0)
    parser.add_argument('--laser-pitch',type=float,default=0)
    parser.add_argument('--laser-yaw',type=float,default=math.pi,help='base_link to laser mounting yaw; 180 degrees from observed front alignment')
    args=parser.parse_args()
    if not 1 <= args.web_port <= 65535: parser.error('Invalid web port')
    if args.mode=='navigation':
        if not args.map:parser.error('navigation needs --map')
        print(validate_map(args.map),flush=True)
    import rclpy
    rclpy.init();probe=rclpy.create_node('robot_stack_startup_check')
    end=time.monotonic()+2
    while time.monotonic()<end:rclpy.spin_once(probe,timeout_sec=0.1)
    names=[name for name,_ in probe.get_node_names_and_namespaces()]
    owned={'lidar_odometry','lidar_imu_odometry','lidar_imu_cartographer','controller_manager','wheel_odometry_node','sllidar_node','cartographer_node','amcl','nav_drive_bridge','mode_manager_node'}
    conflicts=owned.intersection(names)
    probe.destroy_node();rclpy.shutdown()
    if conflicts:raise RuntimeError('Existing stack detected; stop its own launcher first: '+', '.join(sorted(conflicts)))
    existing_viewer = False
    if not args.no_web:
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{args.web_port}/api/state', timeout=.5) as response:
                existing_viewer = bool(json.load(response).get('instance_id'))
        except (OSError, ValueError):
            pass
    # Foreground hardware preparation allows sudo to read from this terminal.
    control=[str(ROOT/'scripts/run_robot_control.sh')]
    if args.no_joystick:control+=['--no-joystick']
    subprocess.run(control+['--prepare-only'],check=True)
    env=os.environ.copy();env.update(ROBOT_USE_WHEEL_ODOMETRY='false',ROBOT_ODOM_PUBLISH_TF='false')
    logs=ROOT/'log'/('session_'+time.strftime('%Y%m%d_%H%M%S'));logs.mkdir(parents=True)
    (logs/'session_options.json').write_text(json.dumps(vars(args),indent=2)+'\n')
    children=[];handles=[]
    def start(label,cmd):
        f=(logs/(label+'.log')).open('w');handles.append(f)
        p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=f,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        children.append((label,p));print(label,'PID',p.pid,'log',f.name,flush=True)
    def stop_handler(signum,frame):raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop_handler)
    try:
        start('control',control)
        start('lidar',[str(ROOT/'scripts/run_lidar.sh')])
        common=[f'laser_{axis}:={getattr(args,"laser_"+axis)}' for axis in ['x','y','z','roll','pitch','yaw']]
        common+=['rviz:='+str(args.rviz).lower()]
        start('local_odometry',['ros2','launch','robot_mapping','lidar_odometry.launch.py']+common[:-1])
        wait_for_base(children,env,logs)
        if args.mode=='mapping':
            start('mapping',[str(ROOT/'scripts/run_mapping.sh'),
                'use_odometry:=true','external_odom_tf:=true','publish_laser_tf:=false']+common)
        else:
            start('navigation',[str(ROOT/'scripts/run_navigation.sh'),'map:='+str(Path(args.map).resolve()),
                'goal_source:='+args.goal_source,'publish_laser_tf:=false']+common)
            print('Set initial pose and goal in the web viewer. Readiness: scripts/check_navigation.sh',flush=True)
        if not args.no_web:
            if not existing_viewer:
                start('web',[str(ROOT/'scripts/start_web_viewer.sh'),'--mode','auto','--port',str(args.web_port)])
            print(f'Web viewer: http://<robot-ip>:{args.web_port}',flush=True)
        print('Ctrl+C stops this session. Logs:',logs,flush=True)
        while True:
            for label,p in children:
                if p.poll() is not None:raise RuntimeError(f'{label} exited ({p.returncode}); see {logs}')
            time.sleep(0.2)
    except KeyboardInterrupt:pass
    finally:
        # Finish cleanup even if Ctrl+C is pressed again while ROS launch exits.
        signal.signal(signal.SIGINT,signal.SIG_IGN)
        signal.signal(signal.SIGTERM,signal.SIG_IGN)
        stop_children(children)
        for f in handles:f.close()


if __name__=='__main__':main()
