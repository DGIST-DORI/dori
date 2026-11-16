"""Image-only tracking state; none of these observations establish identity/range."""
import math
import threading


class LatestImage:
    """A bounded mailbox: inference consumes each received image at most once."""

    def __init__(self):
        self._lock = threading.Lock()
        self._pending = None

    def put(self, message, received_at):
        with self._lock:
            self._pending = (message, received_at)

    def take(self):
        with self._lock:
            pending, self._pending = self._pending, None
            return pending


def stamp_ns(message):
    return message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec


def image_is_fresh(message, now_ns, received_at, now, max_age):
    # Receipt age covers unstamped input and time spent waiting/running inference.
    if not 0 <= now - received_at <= max_age:
        return False
    stamp = stamp_ns(message)
    return stamp == 0 or 0 <= (now_ns - stamp) / 1e9 <= max_age


class VisualTrackMemory:
    """Retain lost camera-local IDs without inventing IoU-based ID associations."""

    def __init__(self, lost_timeout_sec=5.0):
        if not math.isfinite(lost_timeout_sec) or lost_timeout_sec <= 0:
            raise ValueError("lost_timeout_sec must be finite and positive")
        self.lost_timeout_sec = lost_timeout_sec
        self._tracks = {}

    def clear(self):
        self._tracks.clear()

    def update(self, detections, now):
        visible = {d["track_id"] for d in detections if d["track_id"] >= 0}
        for detection in detections:
            track_id = detection["track_id"]
            if track_id >= 0:
                self._tracks[track_id] = (list(detection["bbox"]), now)
        tracks = []
        for track_id, (bbox, last_seen) in list(self._tracks.items()):
            elapsed = max(0.0, now - last_seen)
            if elapsed >= self.lost_timeout_sec:
                del self._tracks[track_id]
                continue
            tracks.append({"track_id": track_id, "bbox": bbox,
                           "state": "tracking" if track_id in visible else "lost",
                           "lost_elapsed_sec": round(elapsed, 3)})
        return {"state": "tracking" if visible else "lost" if tracks else "idle",
                "lost_timeout_sec": self.lost_timeout_sec, "tracks": tracks}


def person_observations(results, width, height, camera_id):
    """Clip detections to the image and reject invalid model output before JSON."""
    detections = []
    for result in results:
        if result.boxes is None:
            continue
        for box in result.boxes:
            coords = box.xyxy[0].tolist()
            confidence = float(box.conf[0])
            if len(coords) != 4 or not all(math.isfinite(v) for v in [*coords, confidence]):
                continue
            if not 0 <= confidence <= 1:
                continue
            x1, y1, x2, y2 = [int(max(0, min(limit, v))) for v, limit in
                              zip(coords, (width, height, width, height))]
            if x2 <= x1 or y2 <= y1:
                continue
            raw_id = float(box.id[0]) if box.id is not None else -1.0
            track_id = int(raw_id) if math.isfinite(raw_id) and raw_id >= 0 and raw_id.is_integer() else -1
            detections.append({
                "camera_id": camera_id, "track_id": track_id,
                "bbox": [x1, y1, x2, y2], "confidence": round(confidence, 3),
                "center_norm": [round((x1 + x2) / (2 * width), 3),
                                round((y1 + y2) / (2 * height), 3)],
                "bbox_area_norm": round((x2 - x1) * (y2 - y1) / (width * height), 4),
                "distance_m": None, "distance_source": "unavailable",
            })
    return detections
