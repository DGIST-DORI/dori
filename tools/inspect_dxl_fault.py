#!/usr/bin/env python3
"""Read fault registers without competing with the stopped robot's ROS serial reader."""
import os,signal,subprocess,sys,time
from pathlib import Path
pid=int(sys.argv[1])
expected='/home/dori/robot_ws/install/dynamixel_sdk_examples/lib/dynamixel_sdk_examples/read_write_node'
assert Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[0].decode()==expected
signal.signal(signal.SIGTERM,lambda *args:sys.exit(2))
try:
    os.kill(pid,signal.SIGSTOP)
    time.sleep(.05)
    output=subprocess.run(['/home/dori/robot_ws/tools/read_dxl_fault'],capture_output=True,text=True,timeout=5)
    print(output.stdout,flush=True)
    print(output.stderr,file=sys.stderr,flush=True)
    Path('/home/dori/robot_ws/log/transform_dxl_fault_20260909.txt').write_text(output.stdout+output.stderr)
finally:
    os.kill(pid,signal.SIGCONT)
