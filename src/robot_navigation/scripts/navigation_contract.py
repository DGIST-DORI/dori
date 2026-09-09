"""Shared file and unit contracts for the real robot navigation pipeline."""
import csv
import math
from pathlib import Path

import yaml
from PIL import Image


def load_points_csv(path):
    path = Path(path)
    points = {}
    with path.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        required = {'name', 'x', 'y', 'yaw_deg', 'frame_id'}
        if not required.issubset(reader.fieldnames or []):
            raise ValueError(f'{path}: CSV needs {sorted(required)}')
        for line, row in enumerate(reader, 2):
            name = (row['name'] or '').strip()
            if not name or name in {'reload', 'list', 'cancel'} or name in points:
                raise ValueError(f'{path}:{line}: empty, reserved or duplicate name')
            values = [float(row[k]) for k in ('x', 'y', 'yaw_deg')]
            if not all(math.isfinite(x) for x in values) or row['frame_id'].strip() != 'map':
                raise ValueError(f'{path}:{line}: finite map-frame coordinates required')
            points[name] = dict(name=name, x=values[0], y=values[1], yaw_deg=values[2], frame_id='map')
    if not points:
        raise ValueError(f'{path}: no destinations')
    return points


def validate_map(path, points_file=None):
    path = Path(path).expanduser().resolve(strict=True)
    config = yaml.safe_load(path.read_text())
    resolution = float(config['resolution'])
    origin = [float(v) for v in config['origin']]
    if resolution <= 0 or not math.isfinite(resolution) or len(origin) != 3 or not all(map(math.isfinite, origin)):
        raise ValueError('Invalid map resolution/origin')
    free = float(config['free_thresh']); occupied = float(config['occupied_thresh'])
    if not 0 <= free < occupied <= 1:
        raise ValueError('Invalid occupancy thresholds')
    image_path = (path.parent / config['image']).resolve(strict=True)
    with Image.open(image_path) as source:
        image = source.convert('L')
    points = load_points_csv(points_file) if points_file else {}
    for name, p in points.items():
        dx, dy = p['x'] - origin[0], p['y'] - origin[1]
        gx = math.floor((math.cos(origin[2])*dx + math.sin(origin[2])*dy)/resolution)
        gy = math.floor((-math.sin(origin[2])*dx + math.cos(origin[2])*dy)/resolution)
        if not (0 <= gx < image.width and 0 <= gy < image.height):
            raise ValueError(f'Destination {name!r} is outside this map')
        gray = image.getpixel((gx, image.height - 1 - gy))/255.0
        probability = gray if int(config.get('negate', 0)) else 1-gray
        if probability >= free:
            raise ValueError(f'Destination {name!r} is not in a known free map cell')
    return dict(map=str(path), image=str(image_path), resolution=resolution,
                width=image.width, height=image.height, points=len(points))


def normalized_twist(v, w, linear_scale, angular_scale, max_v, max_w):
    values = (v, w, linear_scale, angular_scale, max_v, max_w)
    if not all(math.isfinite(x) for x in values) or min(values[2:]) <= 0:
        raise ValueError('Non-finite velocity or invalid limits')
    # Uniform saturation preserves commanded curvature.
    factor = max(1.0, abs(v)/min(max_v, linear_scale), abs(w)/min(max_w, angular_scale))
    return v/factor/linear_scale, w/factor/angular_scale
