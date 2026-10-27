"""Bounded forward displacement converted to a map goal, never a velocity."""
import math


def forward_distance(value):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not .4 <= value <= 3.:
        raise ValueError('Please request a forward move between 0.4 and 3 meters.')
    return float(value)


def forward_goal(pose,distance):
    distance=forward_distance(distance)
    x,y,heading=pose
    if not all(math.isfinite(v) for v in pose):raise ValueError('Robot position is unavailable.')
    return [x+distance*math.cos(heading),y+distance*math.sin(heading),heading]


def forward_reply(distance):
    distance=forward_distance(distance)
    return f'I will move forward {distance:g} '+('meter.' if distance==1. else 'meters.')
