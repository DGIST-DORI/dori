"""TTS backend selection and credential precedence without cloud calls or playback."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from dori_hri import tts_node


@pytest.fixture
def backend(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    monkeypatch.setattr(tts_node, "GTTS_AVAILABLE", True)
    monkeypatch.setattr(tts_node, "GCP_TTS_AVAILABLE", True)
    sdk = SimpleNamespace(TextToSpeechClient=Mock())
    monkeypatch.setattr(tts_node, "texttospeech", sdk, raising=False)
    database = Mock()
    monkeypatch.setattr(tts_node, "TTSDatabaseManager", database)
    logger = Mock()
    node = SimpleNamespace(
        playback_mode="local_only",
        get_parameter=Mock(return_value=SimpleNamespace(value="gcp")),
        get_logger=Mock(return_value=logger),
    )
    key = tmp_path / ".config/dori/google-cloud-tts.json"
    return SimpleNamespace(node=node, sdk=sdk, database=database, logger=logger, key=key)


@pytest.mark.parametrize("engine", ["gcp", "auto"])
def test_cloud_engines_initialize_using_adc(backend, engine):
    backend.node.get_parameter.return_value.value = engine
    tts_node.TTSNode._init_engine(backend.node)
    backend.sdk.TextToSpeechClient.assert_called_once_with()
    assert backend.node.gcp_client is backend.sdk.TextToSpeechClient.return_value
    assert backend.node.db is backend.database.return_value


def test_dori_key_is_loaded_when_no_explicit_adc_file(backend):
    backend.key.parent.mkdir(parents=True)
    backend.key.write_text("{}")
    tts_node.TTSNode._init_engine(backend.node)
    backend.sdk.TextToSpeechClient.from_service_account_file.assert_called_once_with(str(backend.key))
    backend.sdk.TextToSpeechClient.assert_not_called()
    assert backend.node.gcp_client is backend.sdk.TextToSpeechClient.from_service_account_file.return_value


def test_explicit_adc_file_takes_precedence_over_dori_key(backend, monkeypatch):
    backend.key.parent.mkdir(parents=True)
    backend.key.write_text("{}")
    monkeypatch.setenv("GOOGLE_APPLICATION_CREDENTIALS", "/explicit/key.json")
    tts_node.TTSNode._init_engine(backend.node)
    backend.sdk.TextToSpeechClient.assert_called_once_with()
    backend.sdk.TextToSpeechClient.from_service_account_file.assert_not_called()


def test_missing_sdk_logs_gtts_fallback(backend, monkeypatch):
    monkeypatch.setattr(tts_node, "GCP_TTS_AVAILABLE", False)
    tts_node.TTSNode._init_engine(backend.node)
    assert backend.node.gcp_client is None
    backend.sdk.TextToSpeechClient.assert_not_called()
    assert "falling back to gTTS" in backend.logger.warning.call_args.args[0]


def test_invalid_credentials_log_gtts_fallback(backend):
    backend.sdk.TextToSpeechClient.side_effect = ValueError("Invalid credentials")
    tts_node.TTSNode._init_engine(backend.node)
    assert backend.node.gcp_client is None
    backend.database.assert_not_called()
    assert "falling back to gTTS" in backend.logger.error.call_args.args[0]


def test_explicit_gtts_does_not_initialize_cloud(backend):
    backend.node.get_parameter.return_value.value = "gtts"
    tts_node.TTSNode._init_engine(backend.node)
    assert backend.node.gcp_client is None
    backend.sdk.TextToSpeechClient.assert_not_called()
    backend.database.assert_not_called()


def test_browser_only_mode_does_not_require_cloud_or_gtts(backend, monkeypatch):
    backend.node.playback_mode = "publish_only"
    monkeypatch.setattr(tts_node, "GTTS_AVAILABLE", False)
    tts_node.TTSNode._init_engine(backend.node)
    assert backend.node.gcp_client is None
    backend.sdk.TextToSpeechClient.assert_not_called()
