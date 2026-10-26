"""Raw scan check for the swept rear footprint of straight reverse recovery."""
import math
import numpy as np


def rear_clearance(scan, laser_pose, speed, radius=.30, deceleration=.30):
    """Return a drive-gate reason. Caller checks scan age and backup ownership.

    Require observed rear sectors, and check a capsule including stopping
    distance plus scan/control latency. Nav2 separately checks its costmap.
    Invalid/missing rear returns never establish clearance.
    """
    values=np.asarray(scan.ranges,dtype=float)
    if (len(values)<30 or not math.isfinite(scan.angle_increment)
            or scan.angle_increment==0 or not all(math.isfinite(x) for x in (*laser_pose,speed))):
        return 'rear_scan_unknown'
    a=scan.angle_min+np.arange(len(values))*scan.angle_increment+laser_pose[2]
    bearing=np.arctan2(np.sin(a-math.pi),np.cos(a-math.pi))
    valid=np.isfinite(values)&(values>=scan.range_min)&(values<=scan.range_max)
    # Each 15 degree rear sector must contain measured beams. This also rejects
    # a partial-FOV sensor mounted in the wrong direction or a masked rear view.
    for lo in np.linspace(-math.pi/2,math.pi/2,13)[:-1]:
        sector=(bearing>=lo-1e-6)&(bearing<lo+math.pi/12+1e-6)
        if np.count_nonzero(sector)<2 or np.mean(valid[sector])<.5:
            return 'rear_scan_unknown'
    x=laser_pose[0]+values[valid]*np.cos(a[valid])
    y=laser_pose[1]+values[valid]*np.sin(a[valid])
    travel=abs(speed)**2/(2*deceleration)+abs(speed)*.3+.08
    # Distance from each return to the segment swept by the robot center.
    nearest=np.clip(x,-travel,0.)
    if np.any((x<=.05)&((x-nearest)**2+y*y <= (radius+.05)**2)):
        return 'rear_obstacle'
    return 'driving'
