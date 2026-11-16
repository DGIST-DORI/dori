#!/usr/bin/env python3
"""Explicitly download and check RGB perception assets, without opening a camera."""
import argparse
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import zipfile


ROOT = Path(__file__).resolve().parents[1]
MODELS = {
    "person": ("yolov8n.pt", "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt"),
    "pose": ("pose_landmarker_lite.task", "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task"),
    "hands": ("hand_landmarker.task", "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"),
    "face": ("face_landmarker.task", "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"),
}


def check_archive(path):
    """These versioned .pt/.task assets are ZIP containers, not HTML/error pages."""
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise ValueError(f"Missing or invalid model: {path}")
    with zipfile.ZipFile(path) as archive:
        if not archive.namelist() or archive.testzip() is not None:
            raise ValueError(f"Empty or damaged model: {path}")


def download_model(path, url):
    if path.exists():
        check_archive(path)
        print(f"Using existing model: {path}", flush=True)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        print(f"Downloading {path.name}", flush=True)
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            with urllib.request.urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, output)
        check_archive(temporary)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def verify_models(directory, selected, device):
    # In particular, ByteTrack must not pip-install lap during the first frame.
    os.environ["YOLO_AUTOINSTALL"] = "false"
    os.environ.setdefault("YOLO_CONFIG_DIR", str(directory / "ultralytics"))
    import lap  # noqa: F401
    import numpy as np
    import torch
    import torchvision
    from ultralytics import YOLO

    print(f"torch={torch.__version__}, torchvision={torchvision.__version__}, "
          f"CUDA build={torch.version.cuda}, CUDA available={torch.cuda.is_available()}", flush=True)
    # Exercise the compiled extension too: importing torchvision alone is insufficient.
    torchvision.ops.nms(torch.tensor([[0., 0., 10., 10.]]), torch.tensor([1.]), 0.5)
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    model = YOLO(str(directory / MODELS["person"][0]))
    model.track(frame, device=device, classes=[0], tracker="bytetrack.yaml",
                persist=True, verbose=False)
    print("YOLO + ByteTrack initialization/inference passed (synthetic frame).", flush=True)

    if len(selected) == 1:
        return
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision

    image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame)
    factories = {
        "pose": (vision.PoseLandmarker, vision.PoseLandmarkerOptions, {"num_poses": 2}),
        "hands": (vision.HandLandmarker, vision.HandLandmarkerOptions, {"num_hands": 1}),
        "face": (vision.FaceLandmarker, vision.FaceLandmarkerOptions,
                 {"num_faces": 1, "output_face_blendshapes": True}),
    }
    for name in selected[1:]:
        factory, options, extra = factories[name]
        with factory.create_from_options(options(
            base_options=BaseOptions(model_asset_path=str(directory / MODELS[name][0])),
            running_mode=vision.RunningMode.VIDEO, **extra,
        )) as landmarker:
            landmarker.detect_for_video(image, 0)
            landmarker.detect_for_video(image, 33)
        print(f"MediaPipe {name} initialization/inference passed (synthetic frames).", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for feature in ("pose", "hands", "face"):
        parser.add_argument(f"--{feature}", action="store_true", help=f"Also prepare the {feature} model")
    parser.add_argument("--model-dir", type=Path, default=ROOT / ".state/vision")
    parser.add_argument("--device", default="cpu", help="YOLO device for the check (default: cpu)")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--download-only", action="store_true", help="Download assets without ML imports")
    mode.add_argument("--check-only", action="store_true", help="Check local assets without downloading them")
    args = parser.parse_args(argv)
    directory = args.model_dir.expanduser().resolve()
    selected = ["person", *(key for key in ("pose", "hands", "face") if getattr(args, key))]
    try:
        for name in selected:
            filename, url = MODELS[name]
            if args.check_only:
                check_archive(directory / filename)
            else:
                download_model(directory / filename, url)
        if not args.download_only:
            verify_models(directory, selected, args.device)
    except Exception as error:
        print(f"Perception preparation failed: {error}\n"
              "See ros2_ws/src/dori_perception/README.md for package/model setup. "
              "Move invalid model files aside before retrying.", file=sys.stderr)
        return 1
    print(f"Perception assets ready: {directory}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
