"""Planar ROS geometry and occupancy validation shared by the web endpoints."""
import math


def yaw(q):
    return math.atan2(2*(q.w*q.z+q.x*q.y), 1-2*(q.y*q.y+q.z*q.z))


def pose_values(data):
    values = [data.get(k) for k in ('x', 'y', 'yaw')]
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
        raise ValueError('x, y, yaw must be finite numbers')
    if max(abs(values[0]), abs(values[1])) > 1e5:
        raise ValueError('Position outside supported range')
    return [float(values[0]), float(values[1]), math.remainder(values[2], 2*math.pi)]


def free_cell(grid, x, y):
    if grid is None:
        raise ValueError('지도 미수신')
    info = grid.info
    angle = yaw(info.origin.orientation)
    dx, dy = x-info.origin.position.x, y-info.origin.position.y
    col = math.floor((math.cos(angle)*dx+math.sin(angle)*dy) / info.resolution)
    row = math.floor((-math.sin(angle)*dx+math.cos(angle)*dy) / info.resolution)
    if not 0 <= col < info.width or not 0 <= row < info.height:
        raise ValueError('지도 밖의 위치입니다')
    if not 0 <= grid.data[row*info.width+col] < 25:
        raise ValueError('빈 공간을 선택하세요 (장애물 또는 미확인 영역)')
