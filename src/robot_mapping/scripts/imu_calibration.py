"""Explicit, measured IMU calibration; never infer yaw from gravity alone."""
from pathlib import Path
import math
import yaml


def load_calibration(path):
    data=yaml.safe_load(Path(path).read_text())
    if not isinstance(data,dict) or data.get('verified') is not True:
        raise ValueError('IMU calibration is unverified: measure mounting axes and stationary gyro bias first')
    for key in ['xyz_m','rpy_rad','gyro_bias_rad_s']:
        values=data.get(key)
        if not isinstance(values,list) or len(values)!=3 or not all(isinstance(v,(float,int)) and not isinstance(v,bool) and math.isfinite(v) for v in values):
            raise ValueError(key+' must contain three measured finite values')
    if data.get('frame_id')!='imu_link':raise ValueError('Expected actual IMU frame imu_link')
    if 'mapping_frame_id' in data and data['mapping_frame_id']!='imu_mapping':
        raise ValueError('Expected body-aligned frame imu_mapping')
    return data
