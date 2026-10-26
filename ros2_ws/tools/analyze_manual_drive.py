#!/usr/bin/env python3
"""Summarize paired manual input / protected wheel targets / measured motion."""
import argparse
import json
import math
from pathlib import Path


def label(s):
    if s.get('control_mode')!=0 or s.get('action')!=1:return 'inhibited'
    v,w=s.get('manual',[0.,0.])
    if max(abs(v),abs(w))<.05:return 'stop'
    if abs(v)<.05:return 'pivot_left' if w>0 else 'pivot_right'
    direction='forward' if v>0 else 'reverse'
    return direction+('_left' if w>.05 else '_right' if w<-.05 else '')


def summarize(rows):
    groups=[]
    for sample in rows:
        name=label(sample)
        if not groups or groups[-1][0]!=name:groups.append((name,[]))
        groups[-1][1].append(sample)
    result=[]
    for name,g in groups:
        duration=g[-1]['t']-g[0]['t']
        if name in ('inhibited','stop') or duration<.35:continue
        od=[s for s in g if s.get('odom') and s['ages'].get('odom',1) < .5]
        if len(od)<2:continue
        a,b=od[0]['odom'],od[-1]['odom']
        p,q=a['pose'],b['pose'];dx,dy=q[0]-p[0],q[1]-p[1]
        yaw=0.;last=p[2];stamp=a['stamp']
        for s in od[1:]:
            m=s['odom']
            if m['stamp']<=stamp:continue
            yaw+=math.remainder(m['pose'][2]-last,2*math.pi);last=m['pose'][2];stamp=m['stamp']
        command=[sum(s['manual'][i] for s in g)/len(g) for i in range(2)]
        motors=[s for s in g if 'motor_1' in s and 'motor_2' in s]
        targets=[sum(s['motor_'+str(i)]['velocity'] for s in motors)/len(motors) for i in (1,2)] if motors else None
        enc=[]
        for wheel in ('left_wheel_joint','right_wheel_joint'):
            samples=[s['joints'][wheel]['position'] for s in g if wheel in s.get('joints',{})]
            enc.append(sum(math.remainder(y-x,8*math.pi) for x,y in zip(samples,samples[1:])))
        result.append(dict(kind=name,start_s=round(g[0]['t'],2),duration_s=round(duration,2),
            input=[round(x,3) for x in command],wheel_targets_rad_s=[round(x,3) for x in targets] if targets else None,
            encoder_delta_rad=[round(x,3) for x in enc],lidar_distance_m=round(math.hypot(dx,dy),3),
            lidar_forward_m=round(dx*math.cos(p[2])+dy*math.sin(p[2]),3),lidar_yaw_deg=round(math.degrees(yaw),2)))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('recording');parser.add_argument('--output')
    args=parser.parse_args();rows=[]
    with open(args.recording) as f:
        for line in f:
            try:rows.append(json.loads(line))
            except json.JSONDecodeError:continue # The live writer may be partway through its last line.
    report=dict(samples=len(rows),elapsed_s=round(rows[-1]['t'],1) if rows else 0.,segments=summarize(rows))
    text=json.dumps(report,ensure_ascii=False,indent=2)
    if args.output:Path(args.output).write_text(text+'\n')
    print(text)


if __name__=='__main__':main()
