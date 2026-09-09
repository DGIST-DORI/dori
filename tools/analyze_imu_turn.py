#!/usr/bin/env python3
"""Compare a captured turn with independent 2D laser registration and IMU rates."""
import argparse,json,math
from pathlib import Path
import numpy as np
from scipy.spatial import cKDTree


def register(source,target):
    tree=cKDTree(target);best=None
    for yaw in np.radians([-30,-15,0,15,30]):
        R=np.array([[np.cos(yaw),-np.sin(yaw)],[np.sin(yaw),np.cos(yaw)]]);t=np.zeros(2)
        for _ in range(60):
            moved=source@R.T+t;dist,index=tree.query(moved)
            valid=dist<min(.3,float(np.quantile(dist,.8)))
            if np.count_nonzero(valid)<30:break
            src=moved[valid];dst=target[index[valid]];a=src.mean(axis=0);b=dst.mean(axis=0)
            U,_,Vt=np.linalg.svd((src-a).T@(dst-b));step=Vt.T@U.T
            if np.linalg.det(step)<0:Vt[-1]*=-1;step=Vt.T@U.T
            shift=b-step@a;R=step@R;t=step@t+shift
            if np.linalg.norm(shift)<1e-6 and abs(math.atan2(step[1,0],step[0,0]))<1e-6:break
        d,_=tree.query(source@R.T+t);mask=d<.15
        if mask.sum()<30:continue
        rmse=float(np.sqrt(np.mean(d[mask]**2)));fraction=float(mask.mean())
        candidate={'yaw_rad':math.atan2(R[1,0],R[0,0]),'translation_m':t.tolist(),'rmse_m':rmse,'inlier_fraction':fraction}
        score=float(np.mean(np.minimum(d,.3)**2))
        if best is None or score<best[0]:best=(score,candidate)
    return best[1] if best else None


def points(scan):
    rr=np.array([np.nan if x is None else x for x in scan['ranges']])
    aa=scan['angle_min']+np.arange(len(rr))*scan['angle_increment']
    ok=np.isfinite(rr)&(rr>.15)&(rr<8)
    return np.column_stack((rr[ok]*np.cos(aa[ok]),rr[ok]*np.sin(aa[ok])))


def analyze(path):
    data=json.loads(Path(path).read_text());rows=data['samples'];out={'trial_report':data['report'],'steps':[]}
    baseline=[r for r in rows if r['topic']=='imu' and r['phase']=='baseline']
    bias=np.mean([r['gyro'] for r in baseline],axis=0);acc=np.mean([r['accel'] for r in baseline],axis=0)
    up=acc/np.linalg.norm(acc)
    out.update(baseline_bias_rad_s=bias.tolist(),sensor_up_assuming_specific_force=up.tolist(),mounting_verified=False)
    before_phase='baseline'
    for phase in [s['name'] for s in data['report'].get('steps',[])]:
        before=[r for r in rows if r['phase']==before_phase and r['topic']=='scan']
        after=[r for r in rows if r['phase']==phase+'_settle' and r['topic']=='scan']
        imu=[r for r in rows if r['phase'] in [phase,phase+'_settle'] and r['topic']=='imu']
        odom0=[r for r in rows if r['phase']==before_phase and r['topic']=='odom']
        odom1=[r for r in rows if r['phase']==phase+'_settle' and r['topic']=='odom']
        if not (before and after and imu and odom0 and odom1):continue
        tt=np.array([r['stamp'] for r in imu]);gg=np.array([r['gyro'] for r in imu])-bias
        integ=np.trapz(gg,tt,axis=0)
        comparisons=[register(points(scan),points(before[-1])) for scan in after[-3:]]
        out['steps'].append({'phase':phase,'laser_after_to_before':comparisons,
            'gyro_integral_xyz_rad':integ.tolist(),'gyro_about_gravity_rad':float(integ@up),
            'gyro_peak_bias_corrected_rad_s':np.max(np.abs(gg),axis=0).tolist(),
            'odom_delta_xy_m':[odom1[-1][key]-odom0[-1][key] for key in ['x','y']],
            'odom_delta_yaw_rad':math.remainder(odom1[-1]['yaw']-odom0[-1]['yaw'],2*math.pi)})
        before_phase=phase+'_settle'
    return out

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('capture');p.add_argument('--output',required=True);a=p.parse_args()
    result=analyze(a.capture);Path(a.output).write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
