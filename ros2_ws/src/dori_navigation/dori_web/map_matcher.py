"""Bounded scan-to-map search around an approximate user position."""
import math
import numpy as np
from scipy.ndimage import distance_transform_edt


class MapMatcher:
    def __init__(self, grid, resolution, origin):
        self.grid=np.asarray(grid,dtype=np.int16)
        self.resolution=float(resolution);self.origin=np.asarray(origin,dtype=float)
        if self.grid.ndim!=2 or self.resolution<=0 or not np.any(self.grid>=65):
            raise ValueError('위치 탐색에 필요한 지도 장애물 정보가 없습니다')
        self.distance=distance_transform_edt(self.grid<65)*self.resolution
        self.distance[self.grid<0]=2.

    def cells(self,x,y):
        dx=x-self.origin[0];dy=y-self.origin[1];c=math.cos(self.origin[2]);s=math.sin(self.origin[2])
        return np.floor((c*dx+s*dy)/self.resolution).astype(int),np.floor((-s*dx+c*dy)/self.resolution).astype(int)

    def scores(self,poses,points):
        result=[];fractions=[]
        for start in range(0,len(poses),256):
            p=poses[start:start+256];c=np.cos(p[:,2,None]);s=np.sin(p[:,2,None])
            x=p[:,0,None]+c*points[:,0]-s*points[:,1]
            y=p[:,1,None]+s*points[:,0]+c*points[:,1]
            ix,iy=self.cells(x,y);inside=(ix>=0)&(iy>=0)&(ix<self.grid.shape[1])&(iy<self.grid.shape[0])
            ix=np.clip(ix,0,self.grid.shape[1]-1);iy=np.clip(iy,0,self.grid.shape[0]-1)
            known=inside&(self.grid[iy,ix]>=0)
            d=np.where(known,self.distance[iy,ix],2.)
            score=np.mean(np.exp(-.5*(d/.15)**2),axis=1)
            fraction=np.mean(d<.25,axis=1)
            cx,cy=self.cells(p[:,0],p[:,1]);valid=(cx>=0)&(cy>=0)&(cx<self.grid.shape[1])&(cy<self.grid.shape[0])
            cx=np.clip(cx,0,self.grid.shape[1]-1);cy=np.clip(cy,0,self.grid.shape[0]-1)
            valid&=(self.grid[cy,cx]>=0)&(self.grid[cy,cx]<25)&(self.distance[cy,cx]>.20)
            score=np.where(valid,score,-1.)
            result.extend(score);fractions.extend(fraction)
        return np.asarray(result),np.asarray(fractions)

    @staticmethod
    def lattice(center,span,step,angle_span,angle_step):
        x=np.arange(-span,span+step/2,step)+center[0]
        y=np.arange(-span,span+step/2,step)+center[1]
        a=np.arange(-angle_span,angle_span+angle_step/2,angle_step)+center[2]
        return np.stack(np.meshgrid(x,y,a,indexing='ij'),axis=-1).reshape(-1,3)

    def search(self,points,initial,radius=1.5):
        points=np.asarray(points,dtype=float)
        points=points[np.isfinite(points).all(axis=1)]
        if len(points)<50:raise ValueError('위치 탐색에 사용할 LiDAR 점이 부족합니다')
        points=points[::max(1,math.ceil(len(points)/180))]
        initial=np.asarray(initial,dtype=float)
        poses=self.lattice(initial,radius,.25,math.pi,math.radians(5))
        scores,_=self.scores(poses,points)
        order=np.argsort(scores)[::-1];seeds=[]
        for index in order:
            p=poses[index]
            if all(np.linalg.norm(p[:2]-q[:2])>.35 or abs(math.remainder(p[2]-q[2],2*math.pi))>math.radians(15) for q in seeds):
                seeds.append(p)
            if len(seeds)==4:break
        candidates=np.vstack([self.lattice(p,.25,.05,math.radians(6),math.radians(1)) for p in seeds])
        bounded=np.linalg.norm(candidates[:,:2]-initial[:2],ord=np.inf,axis=1)<=radius+.05
        candidates=candidates[bounded]
        scores,fractions=self.scores(candidates,points);best=int(np.argmax(scores));pose=candidates[best].copy()
        if scores[best]<.45 or fractions[best]<.55:
            raise ValueError('주변 지도와 LiDAR가 충분히 맞지 않습니다. 실제 위치 주변을 다시 선택하세요')
        distinct=(np.linalg.norm(candidates[:,:2]-pose[:2],axis=1)>.6)|(
            np.abs(np.arctan2(np.sin(candidates[:,2]-pose[2]),np.cos(candidates[:,2]-pose[2])))>math.radians(25))
        alternative=float(np.max(scores[distinct])) if np.any(distinct) else 0.
        if alternative>scores[best]-.025:
            # Use the supplied approximate heading only to disambiguate truly
            # symmetric rooms, never to force a poor scan match into place.
            competitive=scores>scores[best]-.015
            offsets=np.linalg.norm(candidates[:,:2]-initial[:2],axis=1)/radius
            offsets+=np.abs(np.arctan2(np.sin(candidates[:,2]-initial[2]),np.cos(candidates[:,2]-initial[2])))/math.pi
            best=int(np.argmin(np.where(competitive,offsets,np.inf)));pose=candidates[best].copy()
        pose[2]=math.remainder(pose[2],2*math.pi)
        return dict(pose=pose.tolist(),score=float(scores[best]),matched_fraction=float(fractions[best]),
                    ambiguous=bool(alternative>scores[best]-.025),search_radius=float(radius))

    def refine(self,points,initial,radius=.6,angle_span=math.radians(15)):
        """Local tracking correction; never search the opposite heading."""
        points=np.asarray(points,dtype=float)
        points=points[np.isfinite(points).all(axis=1)]
        if len(points)<50:raise ValueError('정합에 사용할 LiDAR 점이 부족합니다')
        points=points[::max(1,math.ceil(len(points)/180))]
        initial=np.asarray(initial,dtype=float)
        poses=np.vstack((self.lattice(initial,radius,.15,angle_span,math.radians(3)),initial))
        scores,_=self.scores(poses,points)
        seeds=[]
        for index in np.argsort(scores)[::-1]:
            p=poses[index]
            if all(np.linalg.norm(p[:2]-q[:2])>.20 or abs(math.remainder(p[2]-q[2],2*math.pi))>math.radians(5) for q in seeds):seeds.append(p)
            if len(seeds)==4:break
        poses=np.vstack([initial,*[self.lattice(p,.15,.025,math.radians(3),math.radians(.5)) for p in seeds]])
        angular=np.abs(np.arctan2(np.sin(poses[:,2]-initial[2]),np.cos(poses[:,2]-initial[2])))
        poses=poses[(np.linalg.norm(poses[:,:2]-initial[:2],axis=1)<=radius+1e-6)&(angular<=angle_span+1e-6)]
        scores,fractions=self.scores(poses,points);best=int(np.argmax(scores));pose=poses[best].copy()
        distinct=(np.linalg.norm(poses[:,:2]-pose[:2],axis=1)>.20)|(
            np.abs(np.arctan2(np.sin(poses[:,2]-pose[2]),np.cos(poses[:,2]-pose[2])))>math.radians(5))
        alternative=float(np.max(scores[distinct])) if np.any(distinct) else -1.
        current,_=self.scores(initial[None,:],points)
        pose[2]=math.remainder(pose[2],2*math.pi)
        return dict(pose=pose.tolist(),score=float(scores[best]),matched_fraction=float(fractions[best]),
                    current_score=float(current[0]),ambiguous=alternative>scores[best]-.025)
