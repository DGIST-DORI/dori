"""Asset staging must survive failure and support checks without model downloads."""
import importlib.util
import io
from pathlib import Path
from unittest.mock import Mock
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("prepare_perception", ROOT / "scripts/prepare_perception.py")
prepare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(prepare)


def model_archive():
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("model.bin", b"synthetic model data")
    return data.getvalue()


def test_download_preserves_existing_assets_and_can_stage_pose_without_ml(tmp_path, monkeypatch):
    person = tmp_path / "yolov8n.pt"
    person.write_bytes(model_archive())
    existing = person.read_bytes()
    request = Mock(side_effect=lambda *a, **kw: io.BytesIO(model_archive()))
    monkeypatch.setattr(prepare.urllib.request, "urlopen", request)
    verify = Mock(side_effect=AssertionError("download-only must not import ML libraries"))
    monkeypatch.setattr(prepare, "verify_models", verify)
    assert prepare.main(["--pose", "--download-only", "--model-dir", str(tmp_path)]) == 0
    assert person.read_bytes() == existing
    assert (tmp_path / "pose_landmarker_lite.task").is_file()
    request.assert_called_once_with(prepare.MODELS["pose"][1], timeout=60)
    verify.assert_not_called()


@pytest.mark.parametrize("failure", ["interrupted", "html", "empty_zip"])
def test_failed_download_does_not_leave_a_model_or_partial_file(tmp_path, monkeypatch, failure):
    class InterruptedResponse(io.BytesIO):
        def read(self, *args):
            raise OSError("connection lost")

    response = InterruptedResponse() if failure == "interrupted" else io.BytesIO(b"<html>Error</html>")
    if failure == "empty_zip":
        response = io.BytesIO()
        with zipfile.ZipFile(response, "w"):
            pass
        response.seek(0)
    monkeypatch.setattr(prepare.urllib.request, "urlopen", Mock(return_value=response))
    assert prepare.main(["--download-only", "--model-dir", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []


def test_check_only_requires_local_models_and_never_downloads(tmp_path, monkeypatch):
    request = Mock(side_effect=AssertionError("unexpected network access"))
    verify = Mock()
    monkeypatch.setattr(prepare.urllib.request, "urlopen", request)
    monkeypatch.setattr(prepare, "verify_models", verify)
    argv = ["--pose", "--check-only", "--model-dir", str(tmp_path)]
    assert prepare.main(argv) == 1
    verify.assert_not_called()
    for name in ("person", "pose"):
        (tmp_path / prepare.MODELS[name][0]).write_bytes(model_archive())
    assert prepare.main(argv) == 0
    verify.assert_called_once_with(tmp_path, ["person", "pose"], "cpu")
    request.assert_not_called()


def test_invalid_existing_model_is_not_overwritten(tmp_path, monkeypatch):
    model = tmp_path / "yolov8n.pt"
    model.write_bytes(b"bad preexisting file")
    request = Mock()
    monkeypatch.setattr(prepare.urllib.request, "urlopen", request)
    assert prepare.main(["--download-only", "--model-dir", str(tmp_path)]) == 1
    assert model.read_bytes() == b"bad preexisting file"
    request.assert_not_called()
