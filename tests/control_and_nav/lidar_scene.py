"""Analytic ray intersections, independent of the scan matcher."""
import math
import numpy as np

WALLS = np.array([
    [-5., -4., 6., -4.], [6., -4., 6., 5.], [6., 5., -5., 5.], [-5., 5., -5., -4.],
    [2., 1., 3., 1.], [3., 1., 3., 2.], [3., 2., 2., 2.], [2., 2., 2., 1.],
    [-3., 1., -2., 2.5], [-2., 2.5, -3., 3.],
])


def ranges(pose, mounting=(0., 0., 0.), count=720, noise=0., seed=1):
    x, y, yaw = pose
    mx, my, ma = mounting
    origin = np.array([x+math.cos(yaw)*mx-math.sin(yaw)*my,
                       y+math.sin(yaw)*mx+math.cos(yaw)*my])
    angles = -math.pi + np.arange(count)*2*math.pi/count + yaw + ma
    direction = np.column_stack((np.cos(angles), np.sin(angles)))
    segments = WALLS[:, 2:]-WALLS[:, :2]
    offset = WALLS[:, :2]-origin
    denominator = direction[:, 0,None]*segments[None,:,1]-direction[:, 1,None]*segments[None,:,0]
    denominator = np.where(np.abs(denominator)<1e-10, 1e-10, denominator)
    distance = (offset[:,0]*segments[:,1]-offset[:,1]*segments[:,0])[None,:]/denominator
    along = (offset[None,:,0]*direction[:,1,None]-offset[None,:,1]*direction[:,0,None])/denominator
    valid = (distance>0)&(along>=0)&(along<=1)
    result = np.min(np.where(valid,distance,np.inf),axis=1)
    if noise:
        result += np.random.default_rng(seed).normal(0,noise,len(result))
    return result
