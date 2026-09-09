"""Rigid sensor vector/covariance rotation into a body-aligned IMU frame."""
import math

def rotation(rpy):
    r,p,y=rpy;cr,sr=math.cos(r),math.sin(r);cp,sp=math.cos(p),math.sin(p);cy,sy=math.cos(y),math.sin(y)
    return [[cy*cp,cy*sp*sr-sy*cr,cy*sp*cr+sy*sr],
            [sy*cp,sy*sp*sr+cy*cr,sy*sp*cr-cy*sr],[-sp,cp*sr,cp*cr]]

def vector(matrix,values):
    return [sum(matrix[i][j]*values[j] for j in range(3)) for i in range(3)]

def covariance(matrix,values):
    if values[0]<0:return list(values)
    return [sum(matrix[i][a]*values[3*a+b]*matrix[j][b] for a in range(3) for b in range(3)) for i in range(3) for j in range(3)]
