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

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src/robot_navigation/scripts'))
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
                capture_output=True,text=True,env=env,timeout=min(20,max(.1,deadline-time.monotonic())))
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
    parser.add_argument('mode',choices=['mapping','navigation','measure'])
    parser.add_argument('--mapping-odometry',choices=['wheel','lidar'],default='wheel')
    parser.add_argument('--imu-calibration',help='Verified IMU calibration YAML for mapping only')
    parser.add_argument('--odom-scale',type=float,default=1.0,help='Measured wheel odometry distance/yaw multiplier; motor commands unchanged')
    parser.add_argument('--distance',type=float,default=1.0,help='Actual measured ground distance for measure mode, in metres')
    parser.add_argument('--map')
    parser.add_argument('--points')
    parser.add_argument('--no-joystick',action='store_true')
    parser.add_argument('--rviz',action='store_true')
    parser.add_argument('--laser-x',type=float,default=0)
    parser.add_argument('--laser-y',type=float,default=0)
    parser.add_argument('--laser-z',type=float,default=0)
    parser.add_argument('--laser-roll',type=float,default=0)
    parser.add_argument('--laser-pitch',type=float,default=0)
    parser.add_argument('--laser-yaw',type=float,default=0)
    args=parser.parse_args()
    if not math.isfinite(args.distance) or args.distance<=0:parser.error("--distance must be finite and positive")
    if not math.isfinite(args.odom_scale) or args.odom_scale<=0:parser.error("--odom-scale must be finite and positive")
    if args.imu_calibration:
        if args.mode!='mapping':parser.error('--imu-calibration is mapping-only')
        sys.path.insert(0,str(ROOT/'src/robot_mapping/scripts'))
        from imu_calibration import load_calibration
        load_calibration(args.imu_calibration)
    if args.mode=='navigation':
        if not args.map or not args.points:parser.error('navigation needs --map and --points')
        print(validate_map(args.map,args.points),flush=True)
    import rclpy
    rclpy.init();probe=rclpy.create_node('robot_stack_startup_check')
    end=time.monotonic()+2
    while time.monotonic()<end:rclpy.spin_once(probe,timeout_sec=0.1)
    names=[name for name,_ in probe.get_node_names_and_namespaces()]
    owned={'controller_manager','wheel_odometry_node','sllidar_node','cartographer_node','amcl','nav_drive_bridge','mode_manager_node'}
    conflicts=owned.intersection(names)
    probe.destroy_node();rclpy.shutdown()
    if conflicts:raise RuntimeError('Existing stack detected; stop its own launcher first: '+', '.join(sorted(conflicts)))
    # Foreground hardware preparation allows sudo to read from this terminal.
    control=[str(ROOT/'scripts/run_robot_control.sh')]
    if args.no_joystick:control+=['--no-joystick']
    subprocess.run(control+['--prepare-only'],check=True)
    env=os.environ.copy();env['ROBOT_ODOM_PUBLISH_TF']='true';env['ROBOT_ODOM_SCALE']=str(args.odom_scale)
    print(f'Wheel odometry scale: {args.odom_scale:g} (distance and yaw; motor commands unchanged)',flush=True)
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
        wait_for_base(children,env,logs)
        common=[f'laser_{axis}:={getattr(args,"laser_"+axis)}' for axis in ['x','y','z','roll','pitch','yaw']]
        common+=['rviz:='+str(args.rviz).lower()]
        if args.mode=='mapping':
            mapping_args=[str(ROOT/'scripts/run_mapping.sh'),
                'use_wheel_odometry:='+str(args.mapping_odometry=='wheel').lower(),
                'external_odom_tf:=true']
            if args.imu_calibration:
                mapping_args.append('imu_calibration_file:='+str(Path(args.imu_calibration).resolve()))
            start('mapping',mapping_args+common)
        elif args.mode=='measure':
            laser_args=[]
            for axis in ['x','y','z','roll','pitch','yaw']:
                laser_args+=['--'+axis,str(getattr(args,'laser_'+axis))]
            start('laser_tf',['ros2','run','tf2_ros','static_transform_publisher']+laser_args+['--frame-id','base_link','--child-frame-id','laser'])
            def check_children():
                for label,p in children:
                    if p.poll() is not None:raise RuntimeError(f'{label} exited; see {logs}')
            from measure_odometry import run_measurement
            run_measurement(args.distance,args.odom_scale,logs,check_children)
            return
        else:
            start('navigation',[str(ROOT/'scripts/run_navigation.sh'),'map:='+str(Path(args.map).resolve()),
                                'named_points_file:='+str(Path(args.points).resolve())]+common)
            print('Set AMCL initial pose in RViz or scripts/set_initial_pose.sh x y yaw_deg.',flush=True)
            print('Check readiness: scripts/check_navigation.sh. Send text: scripts/navigate.sh "destination".',flush=True)
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
