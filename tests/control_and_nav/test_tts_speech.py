"""Speech requests select a language and preserve DORI/DGIST pronunciations."""

import json
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import Mock
import xml.etree.ElementTree as ET

import pytest

from dori_hri import tts_node
from dori_hri.tts_speech import speech_language, speech_ssml, spoken_text


@pytest.mark.parametrize("text,fallback,expected", [
    ("Hello, I'm DORI. Welcome to DGIST!", "ko", "en-US"),
    ("Dori", "ko", "en-US"),
    ("안녕하세요. DORI입니다.", "en", "ko-KR"),
    ("DGIST 도서관으로 안내합니다.", "ko", "ko-KR"),
    ("도리", "en", "ko-KR"),
    ("123!", "en-US", "en-US"),
    ("123!", "ko", "ko-KR"),
])
def test_language_is_selected_from_each_utterance(text, fallback, expected):
    assert speech_language(text, fallback) == expected


def test_ssml_pronounces_names_without_executing_input_markup():
    text = ('DORI & Dori\'s <break time="9s"/> dori, Doric, Midori, DORI_2, DORI2; '
            "DGIST, Dgist's, dgist, DGISTian, DGIST_2, DGIST2")
    root = ET.fromstring(speech_ssml(text, "en-US-Neural2-F"))
    assert "".join(root.itertext()) == text
    assert root.find("break") is None
    phonemes = root.findall("phoneme")
    assert [p.text for p in phonemes] == ["DORI", "Dori", "dori", "DGIST", "Dgist", "dgist"]
    assert all(p.get("alphabet") == "ipa" for p in phonemes)
    assert [p.get("ph") for p in phonemes] == ["ˈdɔːri"] * 3 + ["diːˈdʒist"] * 3


@pytest.mark.parametrize("tier", ["Neural2", "Wavenet", "Standard"])
def test_korean_name_uses_compatible_english_voice_for_requested_phonemes(tier):
    text = "저는 DORI입니다. Dori가 DGIST를 안내할게요. Dgist의 캠퍼스입니다."
    root = ET.fromstring(speech_ssml(text, f"ko-KR-{tier}-A"))
    assert "".join(root.itertext()) == text
    assert [v.get("name") for v in root.findall("voice")] == [f"en-US-{tier}-F"] * 4
    assert [p.get("ph") for p in root.findall("voice/phoneme")] == ["ˈdɔːri"] * 2 + ["diːˈdʒist"] * 2


@pytest.mark.parametrize("text,language,expected", [
    ("I'm DORI. Dori's here! dori", "en-US", "I'm Dory. Dory's here! Dory"),
    ("DORI입니다. Dori가 안내해요.", "ko-KR", "도리입니다. 도리가 안내해요."),
    ("Doric Midori DORI2 DORI_id", "en-US", "Doric Midori DORI2 DORI_id"),
    ("DGIST, Dgist's campus, dgist", "en-US", "dee jist, dee jist's campus, dee jist"),
    ("DORI가 DGIST를 안내합니다.", "ko-KR", "도리가 디지스트를 안내합니다."),
    ("DGISTian DGIST2 DGIST_id", "en-US", "DGISTian DGIST2 DGIST_id"),
])
def test_plain_text_fallback_only_changes_the_name(text, language, expected):
    assert spoken_text(text, language) == expected


@pytest.fixture
def synthesis(monkeypatch):
    sdk = SimpleNamespace(
        SynthesisInput=Mock(side_effect=lambda **kw: SimpleNamespace(**kw)),
        VoiceSelectionParams=Mock(side_effect=lambda **kw: SimpleNamespace(**kw)),
        AudioConfig=Mock(), AudioEncoding=SimpleNamespace(MP3="mp3"),
    )
    monkeypatch.setattr(tts_node, "texttospeech", sdk, raising=False)
    gtts = Mock()
    monkeypatch.setattr(tts_node, "gTTS", gtts, raising=False)
    client = Mock()
    client.synthesize_speech.return_value.audio_content = b"test-mp3"
    node = SimpleNamespace(
        language="ko", gcp_client=client, db=Mock(), get_logger=Mock(),
        limits={"neural2": 30000, "wavenet": 30000, "standard": 120000},
        playback_mode="publish_only", audio_event_pub=Mock(),
    )
    node.db.get_usage.return_value = dict.fromkeys(node.limits, 0)
    for name in ("_speak_with_waterfall", "_synthesize_gcp", "_synthesize_gtts", "_cleanup_temp_file"):
        setattr(node, name, MethodType(getattr(tts_node.TTSNode, name), node))
    return SimpleNamespace(node=node, gtts=gtts)


@pytest.mark.parametrize("tier,model", [("neural2", "Neural2"), ("wavenet", "Wavenet"), ("standard", "Standard")])
@pytest.mark.parametrize("text,locale,suffix", [("DORI welcomes you to DGIST!", "en-US", "F"), ("Dori가 DGIST를 안내해요.", "ko-KR", "A")])
def test_waterfall_keeps_language_and_pronunciation_in_all_tiers(synthesis, tier, model, text, locale, suffix):
    node = synthesis.node
    for earlier in node.limits:
        if earlier == tier:
            break
        node.limits[earlier] = 0
    path, engine = node._speak_with_waterfall(text)
    try:
        assert engine == tier
        assert Path(path).read_bytes() == b"test-mp3"
        request = node.gcp_client.synthesize_speech.call_args.kwargs
        assert request["voice"].language_code == locale
        assert request["voice"].name == f"{locale}-{model}-{suffix}"
        root = ET.fromstring(request["input"].ssml)
        assert [p.get("ph") for p in root.findall(".//phoneme")] == ["ˈdɔːri", "diːˈdʒist"]
        assert "".join(root.itertext()) == text
        assert request["timeout"] == 10
        assert node.db.add_usage.call_args.args[1:] == (tier, len(request["input"].ssml))
        synthesis.gtts.assert_not_called()
    finally:
        node._cleanup_temp_file(path)


@pytest.mark.parametrize("failure", ["quota", "api"])
@pytest.mark.parametrize("text,lang,spoken", [
    ("DORI welcomes you to DGIST!", "en", "Dory welcomes you to dee jist!"),
    ("Dori가 DGIST를 안내해요.", "ko", "도리가 디지스트를 안내해요."),
])
def test_cloud_fallback_preserves_language_and_name(synthesis, failure, text, lang, spoken):
    node = synthesis.node
    if failure == "quota":
        node.limits = dict.fromkeys(node.limits, 0)
    else:
        node.gcp_client.synthesize_speech.side_effect = RuntimeError("unavailable")
    path, engine = node._speak_with_waterfall(text)
    try:
        assert engine == "gtts"
        synthesis.gtts.assert_called_once_with(text=spoken, lang=lang, slow=False, timeout=(3, 10))
        node.db.add_usage.assert_not_called()
    finally:
        node._cleanup_temp_file(path)


def test_gtts_failure_removes_temporary_audio(synthesis):
    synthesis.gtts.return_value.save.side_effect = RuntimeError("unavailable")
    with pytest.raises(RuntimeError, match="unavailable"):
        synthesis.node._synthesize_gtts("Hello DORI")
    assert not Path(synthesis.gtts.return_value.save.call_args.args[0]).exists()


@pytest.mark.parametrize("kind", ["tts_text", "remote_audio"])
def test_events_keep_display_text_and_supply_browser_language(synthesis, kind):
    payload = {"text": "DORI welcomes you to DGIST!", "engine": "browser"}
    tts_node.TTSNode._publish_audio_event(synthesis.node, kind, payload)
    event = json.loads(synthesis.node.audio_event_pub.publish.call_args.args[0].data)
    assert event["text"] == payload["text"] == "DORI welcomes you to DGIST!"
    assert event["language"] == "en-US"
    assert event["speech_text"] == "Dory welcomes you to dee jist!"
    assert "language" not in payload
