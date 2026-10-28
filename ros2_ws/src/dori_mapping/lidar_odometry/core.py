"""Robust point-to-line ICP against a retained keyframe, in metres/radians.

No wheel velocity, map correction, scale multiplier or IMU integration enters
this estimator. Failed registrations never replace the reference or advance pose.
"""

from dataclasses import dataclass
import math
import numpy as np
from scipy.spatial import cKDTree


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def rotation(yaw):
    c, s = math.cos(yaw), math.sin(yaw)
    return np.array([[c, -s], [s, c]])


def transform(points, pose):
    return np.asarray(points) @ rotation(pose[2]).T + pose[:2]


def compose(a, b):
    return np.r_[rotation(a[2]) @ b[:2] + a[:2], wrap(a[2] + b[2])]


def inverse(pose):
    return np.r_[-rotation(-pose[2]) @ pose[:2], -pose[2]]


def scan_points(
    ranges, angle_min, angle_increment, range_min, range_max, max_points=900
):
    values = np.asarray(ranges, dtype=float)
    if (
        values.ndim != 1
        or len(values) < 20
        or not all(
            map(math.isfinite, (angle_min, angle_increment, range_min, range_max))
        )
        or angle_increment == 0
        or not 0 <= range_min < range_max
    ):
        raise ValueError("invalid_scan_geometry")
    indices = np.arange(0, len(values), max(1, math.ceil(len(values) / max_points)))
    valid = (
        np.isfinite(values[indices])
        & (values[indices] > range_min)
        & (values[indices] < range_max)
    )
    indices = indices[valid]
    angles = angle_min + indices * angle_increment
    return np.column_stack(
        (values[indices] * np.cos(angles), values[indices] * np.sin(angles))
    )


@dataclass(frozen=True)
class Settings:
    max_correspondence: float = 0.35
    max_rmse: float = 0.06
    min_overlap: float = 0.50
    min_points: int = 45
    max_condition: float = 1000.0
    keyframe_distance: float = 0.25
    keyframe_angle: float = 0.20
    keyframe_min_overlap: float = 0.70
    max_linear_speed: float = 2.0
    max_angular_speed: float = 4.0
    max_gap: float = 1.5


@dataclass
class Match:
    pose: np.ndarray
    rmse: float
    overlap: float
    condition: float
    covariance: np.ndarray
    iterations: int


class RegistrationError(ValueError):
    pass


class Reference:
    def __init__(self, points, settings):
        self.points = np.asarray(points)
        self.settings = settings
        if len(points) < settings.min_points:
            raise RegistrationError("too_few_points")
        # Neighbours are used only on a locally straight surface. Range jumps,
        # corners, isolated returns and unsupported lines are excluded.
        tree = cKDTree(points)
        distances, indices = tree.query(points, k=5)
        neighbours = self.points[indices]
        centered = neighbours - neighbours.mean(axis=1, keepdims=True)
        covariance = np.einsum("nki,nkj->nij", centered, centered) / 5
        eigenvalues, eigenvectors = np.linalg.eigh(covariance)
        valid = (
            (distances[:, -1] < 0.65)
            & (eigenvalues[:, 1] > 1e-5)
            & (eigenvalues[:, 0] < 0.08 * eigenvalues[:, 1])
        )
        self.points = self.points[valid]
        self.normals = eigenvectors[valid, :, 0]
        if len(self.points) < settings.min_points:
            raise RegistrationError("insufficient_surfaces")
        self.tree = cKDTree(self.points)

    def match(self, source, initial):
        cfg = self.settings
        pose = np.array(initial, dtype=float)
        converged = False
        for iteration in range(30):
            moved = transform(source, pose)
            distances, indices = self.tree.query(moved)
            normals = self.normals[indices]
            residual = np.sum(normals * (moved - self.points[indices]), axis=1)
            valid = (distances < cfg.max_correspondence) & (np.abs(residual) < 0.20)
            if valid.sum() < cfg.min_points or valid.mean() < cfg.min_overlap:
                raise RegistrationError("insufficient_overlap")
            p, n, residual = moved[valid], normals[valid], residual[valid]
            # Huber loss: moving objects and multipath returns have bounded influence.
            weights = np.minimum(1.0, 0.025 / np.maximum(np.abs(residual), 1e-9))
            jacobian = np.column_stack((n, -n[:, 0] * p[:, 1] + n[:, 1] * p[:, 0]))
            hessian = jacobian.T @ (weights[:, None] * jacobian)
            # Normalize angular units before testing observability (long parallel
            # walls cannot constrain translation along a corridor).
            scale = np.sqrt(np.maximum(np.diag(hessian), 1e-12))
            condition = np.linalg.cond(hessian / np.outer(scale, scale))
            if not math.isfinite(condition) or condition > cfg.max_condition:
                raise RegistrationError("degenerate_geometry")
            delta = np.linalg.solve(hessian, -jacobian.T @ (weights * residual))
            if np.linalg.norm(delta[:2]) > 0.5 or abs(delta[2]) > 0.4:
                raise RegistrationError("registration_jump")
            pose = compose(delta, pose)
            if np.linalg.norm(delta[:2]) < 0.0002 and abs(delta[2]) < 0.0001:
                converged = True
                break
        if not converged:
            raise RegistrationError("not_converged")
        moved = transform(source, pose)
        distances, indices = self.tree.query(moved)
        residual = np.sum(
            self.normals[indices] * (moved - self.points[indices]), axis=1
        )
        valid = (distances < cfg.max_correspondence) & (np.abs(residual) < 0.12)
        overlap = float(valid.mean())
        rmse = (
            float(np.sqrt(np.mean(residual[valid] ** 2))) if valid.any() else math.inf
        )
        if (
            overlap < cfg.min_overlap
            or valid.sum() < cfg.min_points
            or rmse > cfg.max_rmse
        ):
            raise RegistrationError("poor_fit")
        covariance = np.linalg.inv(hessian) * max(rmse**2, 0.005**2)
        return Match(pose, rmse, overlap, float(condition), covariance, iteration + 1)


class Odometry:
    def __init__(self, settings=Settings()):
        self.settings = settings
        self.reference = None
        self.pose = np.zeros(3)
        self.reference_pose = np.zeros(3)
        self.reference_stamp = None
        self.last_stamp = None
        self.last_seen = None
        self.velocity = np.zeros(3)
        self.lost = False

    def update(self, points, stamp):
        if not math.isfinite(stamp) or stamp <= 0:
            raise RegistrationError("invalid_stamp")
        if self.last_seen is not None and stamp <= self.last_seen:
            raise RegistrationError("out_of_order")
        self.last_seen = stamp
        points = np.asarray(points, dtype=float)
        if points.ndim != 2 or points.shape[1] != 2 or not np.isfinite(points).all():
            raise RegistrationError("invalid_points")
        if len(points) < self.settings.min_points:
            raise RegistrationError("too_few_points")
        if self.reference is None:
            reference = Reference(points, self.settings)
            match = reference.match(points, np.zeros(3))
            self.reference = reference
            self.reference_stamp = stamp
            self.last_stamp = stamp
            return match
        dt = stamp - self.last_stamp
        # After a gap, retry the retained reference without extrapolating an
        # old velocity. Successful registration recovers the SAME odom origin;
        # no unobserved motion is hidden by re-anchoring the current scan.
        self.lost = dt > self.settings.max_gap
        prediction = (
            self.pose if self.lost else compose(self.pose, self.velocity * min(dt, 0.3))
        )
        initial = compose(inverse(self.reference_pose), prediction)
        try:
            match = self.reference.match(points, initial)
        except RegistrationError as failure:
            if str(failure) not in (
                "insufficient_overlap",
                "not_converged",
                "poor_fit",
            ):
                raise
            # ICP's nearest-neighbour basin is narrow for a sudden rotation at
            # long range. Search a bounded yaw window before retrying the same
            # point-to-line validation. The reference and odom origin stay fixed.
            span = min(0.65, self.settings.max_angular_speed * dt + 0.08)
            reduced = points[::3]
            candidates = []
            for offset in np.arange(-span, span + 0.02, 0.04):
                guess = initial.copy()
                guess[2] = wrap(guess[2] + offset)
                distances, _ = self.reference.tree.query(transform(reduced, guess))
                score = float(np.mean(np.minimum(distances, 0.6) ** 2))
                candidates.append((score, guess))
            match = None
            for _, guess in sorted(candidates, key=lambda item: item[0])[:3]:
                try:
                    match = self.reference.match(points, guess)
                    break
                except RegistrationError:
                    continue
            if match is None:
                raise failure
        pose = compose(self.reference_pose, match.pose)
        relative = compose(inverse(self.pose), pose)
        if (
            np.linalg.norm(relative[:2]) / dt > self.settings.max_linear_speed
            or abs(relative[2]) / dt > self.settings.max_angular_speed
        ):
            raise RegistrationError("implausible_motion")
        # Twist is expressed in the CURRENT child frame, not the odom frame.
        self.velocity = np.r_[
            rotation(-pose[2]) @ (pose[:2] - self.pose[:2]) / dt,
            wrap(pose[2] - self.pose[2]) / dt,
        ]
        self.pose, self.last_stamp = pose, stamp
        self.lost = False
        # A gimballed scan plane or nearby objects can change while the base is
        # nearly stationary. Refresh a degrading keyframe ONLY after an accepted
        # registration, preserving its measured pose and all rejection checks.
        refresh_surfaces = (
            match.overlap < self.settings.keyframe_min_overlap
            and stamp - self.reference_stamp > 1.0
        )
        if (
            np.linalg.norm(match.pose[:2]) > self.settings.keyframe_distance
            or abs(match.pose[2]) > self.settings.keyframe_angle
            or refresh_surfaces
        ):
            try:
                reference = Reference(points, self.settings)
                reference.match(points, np.zeros(3))
            except RegistrationError:
                pass
            else:
                self.reference, self.reference_pose = reference, pose.copy()
                self.reference_stamp = stamp
        return match
