#!/usr/bin/env python3
"""Fit body response from manual-drive JSONL without changing robot parameters.

Uses post-limiter motor targets and LiDAR acquisition stamps, not instantaneous
joystick labels. Later driving is held out from fitting. Only forward rolling
motion calibrates the autonomous forward-arc model; reverse/pivot trials do not.
"""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.optimize import least_squares


def aligned_samples(rows, radius=.234, separation=.184, scale_v=1.72, scale_w=7.):
    origin=rows[0]['ros_time']
    valid=[s for s in rows if all(k in s for k in ('motor_1','motor_2','joints','odom','manual'))
           and all(s['ages'].get(k,1)<.15 for k in ('motor_1','motor_2','joints'))
           and s.get('control_mode')==0 and s.get('action')==1]
    t=np.array([s['ros_time']-origin for s in valid])
    motors=np.array([[s['motor_1']['velocity'],s['motor_2']['velocity']] for s in valid])
    applied=np.column_stack((radius*motors.mean(axis=1)/scale_v,
                            radius*(motors[:,1]-motors[:,0])/separation/scale_w))
    joint=np.array([[s['joints'][k]['position'] for k in ('left_wheel_joint','right_wheel_joint')] for s in valid])
    joint=np.unwrap(joint,period=8*np.pi,axis=0)
    od={s['odom']['stamp']-origin:s['odom']['pose'] for s in valid if s['ages']['odom']<.5}
    ot=np.array(sorted(od));pose=np.array([od[k] for k in ot]);pose[:,2]=np.unwrap(pose[:,2])
    window=.5;ct=ot[(ot>ot[0]+window/2)&(ot<ot[-1]-window/2)]
    def interval(ts, values):
        lo=np.column_stack([np.interp(ct-window/2,ts,values[:,i]) for i in range(values.shape[1])])
        hi=np.column_stack([np.interp(ct+window/2,ts,values[:,i]) for i in range(values.shape[1])])
        return lo,hi
    lo,hi=interval(ot,pose);heading=(lo[:,2]+hi[:,2])/2
    v=((hi[:,0]-lo[:,0])*np.cos(heading)+(hi[:,1]-lo[:,1])*np.sin(heading))/window
    w=(hi[:,2]-lo[:,2])/window
    jl,jh=interval(t,joint);jv=(jh-jl)/window
    encoder=np.column_stack((radius*jv.mean(axis=1),radius*(jv[:,1]-jv[:,0])/separation))
    requested=np.array([s['manual'] for s in valid])
    active_start=float(t[np.max(np.abs(requested),axis=1)>.05][0])
    return dict(time=ct,v=v,w=w,encoder=encoder,command_time=t,applied=applied,
                requested=requested,pose_time=ot,pose=pose,active_start=active_start)


def response(gain, deadzone, u):
    return gain*np.sign(u)*np.maximum(np.abs(u)-deadzone,0.)


def fit(data):
    ct,t,a=data['time'],data['command_time'],data['applied']
    v,w=data['v'],data['w'];cut=data['active_start']+.67*(ct[-1]-data['active_start'])
    result={}
    for axis,y in enumerate((v,w)):
        best=None
        for delay in np.arange(0,.61,.05):
            u=np.interp(ct-delay,t,a[:,axis]);uv=np.interp(ct-delay,t,a[:,0]);uw=np.interp(ct-delay,t,a[:,1])
            mask=(ct>data['active_start']-2)&(uv>.03)&(abs(uw)<.5)
            if axis:mask&=(v>.08)&(abs(u)>.03)&(abs(w)<2.)
            else:mask&=(v>-.08)&(v<.8)
            train=mask&(ct<cut);test=mask&(ct>=cut)
            if min(train.sum(),test.sum())<30:raise ValueError('Insufficient train/validation driving samples')
            if axis:
                fitted=least_squares(lambda p:p[0]*u[train]-y[train],[1.6],bounds=([.1],[7.]),loss='soft_l1',f_scale=.12)
                gain,deadzone=fitted.x[0],0.
            else:
                fitted=least_squares(lambda p:response(*p,u[train])-y[train],[.65,.24],
                    bounds=([.1,0.],[2.,.7]),loss='soft_l1',f_scale=.04)
                gain,deadzone=fitted.x
            error=np.mean(abs(response(gain,deadzone,u[train])-y[train]))
            if best is None or error<best['train_mae']:
                best=dict(response_gain=float(gain),start_input=float(deadzone),response_delay=float(delay),
                    train_mae=float(error),validation_mae=float(np.mean(abs(response(gain,deadzone,u[test])-y[test]))),
                    train_samples=int(train.sum()),validation_samples=int(test.sum()))
        result['linear' if axis==0 else 'angular']=best
    result['validation_start_s']=float(cut)
    result['encoder_to_lidar_ratio']={
        'linear':float(np.median(data['encoder'][(v>.12)&(data['encoder'][:,0]>.1),0]/v[(v>.12)&(data['encoder'][:,0]>.1)])),
        'angular':float(np.median(data['encoder'][(abs(w)>.2)&(abs(data['encoder'][:,1])>.2),1]/w[(abs(w)>.2)&(abs(data['encoder'][:,1])>.2)]))}
    return result


def plot(data,report,path):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig,axes=plt.subplots(4,1,figsize=(13,9),sharex=True,constrained_layout=True)
    t,ct=data['command_time'],data['time']
    for k,name in enumerate(('linear','angular')):
        axes[2*k].plot(t,data['requested'][:,k],label='Joystick',alpha=.5,lw=1)
        axes[2*k].plot(t,data['applied'][:,k],label='After acceleration limit',lw=1.5)
        axes[2*k].set_ylabel(name+' input')
        axes[2*k+1].plot(ct,data['v' if k==0 else 'w'],label='LiDAR body motion',lw=1.5)
        p=report[name];u=np.interp(ct-p['response_delay'],t,data['applied'][:,k])
        predicted=response(p['response_gain'],p['start_input'],u)
        predicted=np.where(np.interp(ct,t,data['applied'][:,0])>.03,predicted,np.nan)
        axes[2*k+1].plot(ct,predicted,label='Fitted forward rolling response',lw=1,alpha=.8)
        axes[2*k+1].set_ylabel('m/s' if k==0 else 'rad/s')
    for ax in axes:
        ax.axvline(report['validation_start_s'],color='.5',ls='--',lw=1)
        ax.grid(alpha=.2);ax.legend(loc='upper left',fontsize=8,ncol=2)
        ax.set_xlim(data['active_start']-2,ct[-1])
    axes[-1].set_xlabel('Seconds since recording started (dashed line: held-out validation)')
    fig.savefig(path,dpi=150);plt.close(fig)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('recording');parser.add_argument('--output',required=True)
    parser.add_argument('--plot');args=parser.parse_args()
    rows=[json.loads(x) for x in open(args.recording)]
    data=aligned_samples(rows);report=fit(data)
    report.update(recording=args.recording,samples=len(rows),duration_s=rows[-1]['t'],
        method='0.5s LiDAR pose differences; post-limiter motor targets; robust fit; last 33% held out',
        limitations=['Forward rolling model only; reverse and pivot behavior are not calibrated.',
                     'Encoder/body discrepancy can include geometry, gearing and slip; geometry was not changed.',
                     'Validation samples overlap in 0.5s windows and are not statistically independent.'])
    Path(args.output).write_text(json.dumps(report,indent=2)+'\n')
    if args.plot:plot(data,report,args.plot)
    print(json.dumps(report,indent=2))


if __name__=='__main__':main()
