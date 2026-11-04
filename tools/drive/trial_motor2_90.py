#!/usr/bin/env python3
"""Five relative +90-degree round trips for logical motor 2 only."""
import argparse,json,math,signal,time
from pathlib import Path
from trial_bldc_180 import Trial,configuration,command,endpoint_integral,settling_gain,write_report

def ramp(t,distance):
    sign=1 if distance>=0 else -1
    d=abs(distance); acceleration=math.radians(40)
    if d==0:return 0.,0.,0.
    ta=min(math.radians(60)/acceleration,math.sqrt(d/acceleration));v=acceleration*ta
    duration=d/v+ta
    if t<ta:return sign*.5*acceleration*t*t,sign*acceleration*t,duration
    if t<duration-ta:return sign*(.5*acceleration*ta*ta+v*(t-ta)),sign*v,duration
    if t<duration:return sign*(d-.5*acceleration*(duration-t)**2),sign*acceleration*(duration-t),duration
    return sign*d,0.,duration

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');parser.add_argument('--output',type=Path,required=True);parser.add_argument('--angle-deg',type=float,choices=(-720.,90.,180.,720.),default=90.);parser.add_argument('--reference-file',type=Path);parser.add_argument('--to-encoder-zero',action='store_true');parser.add_argument('--rounds',type=int,choices=(3,5),default=5);parser.add_argument('--inspect-only',action='store_true');parser.add_argument('--position-tolerance-deg',type=float,choices=(0.5,1.0),default=1.0);parser.add_argument('--settle-timeout-s',type=float,choices=(15.,30.),default=15.);args=parser.parse_args()
    if args.to_encoder_zero:args.angle_deg=0.;args.reference_file=None
    motor=next(m for m in configuration() if m.logical==2)
    assert motor.can_id==1
    if args.inspect_only:
        trial=Trial([motor])
        try:
            trial.special(motor,0xFD)
            for _ in range(40):
                trial.send(command(motor));time.sleep(.01);trial.receive()
            if not trial.fresh() or not trial.position_stable(2):raise RuntimeError('No fresh stationary feedback')
            position=trial.states[2]['position'];raw=position*motor.sign+motor.offset
            candidates=[]
            for angle in (-720.,720.):
                target=(position+math.radians(angle))*motor.sign+motor.offset
                if motor.pmin+math.radians(1)<target<motor.pmax-math.radians(1):
                    candidates.append(dict(logical_move_deg=angle,target_encoder_deg=math.degrees(target)))
            data=dict(reference_rad=position,encoder_deg=math.degrees(raw),motor=2,can_id=motor.can_id,candidates=candidates,enable_command_sent=False,feedback=trial.states[2])
            write_report(args.output,data);print(json.dumps(data),flush=True)
        finally:trial.bus.close()
        return
    if not args.execute:print('Logical motor 2, CAN 1 only; +90 deg, hold 3 s, return; five rounds; 60 deg/s, 40 deg/s².');return
    def interrupt(*_):raise KeyboardInterrupt('External interruption')
    signal.signal(signal.SIGTERM,interrupt)
    trial=Trial([motor]);report=dict(result='running',motor=2,can_id=1,speed_deg_s=60,accel_deg_s2=40,dwell_s=3,angle_deg=args.angle_deg,rounds=args.rounds,position_tolerance_deg=args.position_tolerance_deg,settle_timeout_s=args.settle_timeout_s,legs=[],holds=[],encoder_zero_command_sent=False)
    reference=None;integral=0.;last=time.monotonic();result=1
    lower,upper=min(0,args.angle_deg)-5,max(0,args.angle_deg)+5
    def tick(goal,velocity,kp,moving):
        nonlocal integral,last
        now=time.monotonic();dt=now-last;last=now
        trial.receive()
        if not trial.fresh():raise RuntimeError('Motor 2 feedback expired')
        state=trial.states[2];rel=math.degrees(state['position']-reference)
        raw=state['position']*motor.sign+motor.offset
        if not motor.pmin+math.radians(.25)<raw<motor.pmax-math.radians(.25):raise RuntimeError('Encoder near representation boundary')
        if not lower<=rel<=upper:raise RuntimeError('Outside authorized relative interval')
        if abs(trial.measured_velocity(2))>math.radians(90) or abs(state['velocity'])>3:raise RuntimeError('Excessive velocity')
        if abs(goal-state['position'])>math.radians(25):raise RuntimeError('Tracking error exceeds 25 degrees')
        integral=endpoint_integral(integral,goal-state['position'],dt,moving=moving)
        trial.send(command(motor,goal,velocity,kp,3,integral));time.sleep(.01)
        return state,rel
    try:
        # Capture the current position while disabled, before enabling any torque.
        trial.special(motor,0xFD)
        for _ in range(40):
            trial.send(command(motor));time.sleep(.01);trial.receive()
        if not trial.fresh() or not trial.position_stable(2):raise RuntimeError('Initial position is not stationary')
        reference=trial.states[2]['position']
        if args.to_encoder_zero:
            start_position=reference
            report['start_encoder_deg']=math.degrees(start_position*motor.sign+motor.offset)
            reference=-motor.offset*motor.sign
            start_relative=math.degrees(start_position-reference)
            lower,upper=min(0,start_relative)-5,max(0,start_relative)+5
            report.update(mode='move_to_encoder_zero',rounds=0)
            print('START_ENCODER_DEG '+str(report['start_encoder_deg']),flush=True)
        if args.reference_file:reference=json.loads(args.reference_file.read_text())['reference_rad']
        report['reference_rad']=reference;report['reference_deg']=math.degrees(reference)
        for target in (reference,reference+math.radians(args.angle_deg)):
            raw=target*motor.sign+motor.offset
            if not motor.pmin<raw<motor.pmax:raise RuntimeError('Target crosses encoder boundary')
        write_report(args.output,report)
        print('REFERENCE '+str(report['reference_deg']),flush=True)
        trial.enabled.add(2);trial.send(command(motor,trial.states[2]['position'],0,45,3));trial.special(motor,0xFC)
        for repetition in range(0,1 if args.to_encoder_zero else args.rounds+1):
            for phase,target_deg in ((('align',0),) if repetition==0 else (('outbound',args.angle_deg),('return',0))):
                trial.receive();start=trial.states[2]['position'];goal=reference+math.radians(target_deg);distance=goal-start
                started=time.monotonic();stable=None
                while True:
                    elapsed=time.monotonic()-started;p,v,duration=ramp(elapsed,distance)
                    state,relative=tick(start+p,v,settling_gain(45,60,elapsed-duration),elapsed<duration)
                    at_goal=elapsed>=duration and abs(relative-target_deg)<=args.position_tolerance_deg and abs(state['velocity'])<.35 and trial.position_stable(2)
                    if at_goal:
                        if stable is None:stable=time.monotonic()
                        elif time.monotonic()-stable>=.5:break
                    else:stable=None
                    if elapsed>duration+args.settle_timeout_s:raise RuntimeError('Arrival timed out')
                leg=dict(round=repetition,phase=phase,target_deg=target_deg,reached_deg=relative,elapsed_s=time.monotonic()-started,temperature_c=state['temperature'])
                report['legs'].append(leg);write_report(args.output,report);print('REACHED '+json.dumps(leg),flush=True)
                if phase=='outbound':
                    held=time.monotonic();positions=[]
                    while time.monotonic()-held<3:
                        _,rel=tick(goal,0,60,False);positions.append(rel)
                        if abs(rel-target_deg)>5:raise RuntimeError('Lost holding position')
                    report['holds'].append(dict(round=repetition,duration_s=time.monotonic()-held,min_deg=min(positions),max_deg=max(positions)))
                    print('HOLD_COMPLETE round '+str(repetition),flush=True)
                trial.samples=trial.samples[-1000:]
        report['result']='success';result=0
    except (Exception,KeyboardInterrupt) as error:
        report.update(result='aborted',reason=str(error),failure_feedback=dict(trial.states));print('ABORT '+str(error),flush=True)
    finally:
        report['stop_errors']=trial.stop();report['last_feedback']=trial.states
        if report['stop_errors']:report['result']='aborted';result=1
        write_report(args.output,report);trial.bus.close();print('FINISHED '+report['result'],flush=True)
    return result
if __name__=='__main__':raise SystemExit(main())
