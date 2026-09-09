#!/usr/bin/env python3
import json,math,argparse
from pathlib import Path
import numpy as np
from analyze_imu_turn import register,points
p=argparse.ArgumentParser();p.add_argument('log');p.add_argument('--output',required=True);a=p.parse_args()
rows=[]
with open(a.log) as f:
    limit=Path(a.log).stat().st_size
    while f.tell()<limit:
        line=f.readline()
        try:r=json.loads(line)
        except json.JSONDecodeError:continue
        if r['elapsed']>=90:rows.append(r)
imu=[r for r in rows if r['topic']=='imu'];odom=[r for r in rows if r['topic']=='odom'];scans=[r for r in rows if r['topic']=='scan']
it=np.array([r['stamp'] for r in imu]);gg=np.array([r['gyro'] for r in imu]);aa=np.array([r['accel'] for r in imu]);ot=np.array([r['stamp'] for r in odom]);ow=np.array([r['w'] for r in odom]);ov=np.array([r['v'] for r in odom])
# Last five seconds are a candidate resting segment; disclose this assumption.
rest=it>it[-1]-5;bias=np.median(gg[rest],axis=0);up=np.median(aa[rest],axis=0);up/=np.linalg.norm(up)
gyaw=(gg-bias)@up
pairs=[]
for i in range(0,len(scans)-1,5):
    x,y=scans[i:i+2];dt=y['stamp']-x['stamp']
    if not .05<dt<.2:continue
    reg=register(points(y),points(x))
    if reg is None or reg['inlier_fraction']<.75 or reg['rmse_m']>.07 or abs(reg['yaw_rad'])>.3:continue
    middle=(x['stamp']+y['stamp'])/2 + x['time_increment']*(len(x['ranges'])-1)/2
    pairs.append({'t':middle,'dt':dt,'laser_w':reg['yaw_rad']/dt,'gyro_w':float(np.interp(middle,it,gyaw)),'odom_w':float(np.interp(middle,ot,ow)),
                  'laser_speed':float(np.linalg.norm(reg['translation_m'])/dt),'odom_v':float(np.interp(middle,ot,ov)),
                  'gyro_xyz':[float(np.interp(middle,it,gg[:,j]-bias[j])) for j in range(3)],'registration':reg})
res={'window_elapsed_s':[rows[0]['elapsed'],rows[-1]['elapsed']],'accepted_scan_pairs':len(pairs),'bias_last5s_assumes_rest':bias.tolist(),'up_axis_assumes_specific_force':up.tolist(),'comparisons':{},'pairs':pairs}
active=[r for r in pairs if abs(r['laser_w'])>.08]
if len(active)>5:
    lw=np.array([r['laser_w'] for r in active])
    for k in ['gyro_w','odom_w']:
        v=np.array([r[k] for r in active]);res['comparisons'][k]={'correlation_with_laser':float(np.corrcoef(lw,v)[0,1]),'gain_to_laser':float(v@lw/(v@v)),'median_abs_rate':float(np.median(np.abs(v))),'sign_agreement':float(np.mean(lw*v>0))}
    res['comparisons']['laser_median_abs_rate']=float(np.median(np.abs(lw)))
    res['comparisons']['gyro_raw_axis_correlations']=[float(np.corrcoef(lw,[r['gyro_xyz'][j] for r in active])[0,1]) for j in range(3)]
res['active_pairs']=len(active)
res['odom_integrated_distance_m']=float(np.trapz(np.abs(ov),ot));res['odom_integrated_abs_yaw_deg']=float(np.degrees(np.trapz(np.abs(ow),ot)))
res['imu_integrated_abs_yaw_deg']=float(np.degrees(np.trapz(np.abs(gyaw),it)))
Path(a.output).write_text(json.dumps(res,indent=2)+'\n');print(json.dumps({k:v for k,v in res.items() if k!='pairs'},indent=2))
