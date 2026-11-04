"""Language and pronunciation policy shared by local and remote TTS synthesis."""

import re
from html import escape


# Match names next to Korean particles, but never inside Latin words/IDs.
NAME_PRONUNCIATIONS = {
    "dori": {"ipa": "ˈdɔːri", "en": "Dory", "ko": "도리"},
    # Use /dʒ/ and stress the second syllable; display text stays DGIST.
    "dgist": {"ipa": "diːˈdʒist", "en": "dee jist", "ko": "디지스트"},
}
KNOWN_NAMES = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(NAME_PRONUNCIATIONS) + r")(?![A-Za-z0-9_])",
    re.IGNORECASE,
)
HANGUL = re.compile(r"[\u1100-\u11ff\u3130-\u318f\ua960-\ua97f\uac00-\ud7ff]")
GCP_VOICES = {
    "ko-KR": {
        "neural2": "ko-KR-Neural2-A",
        "wavenet": "ko-KR-Wavenet-A",
        "standard": "ko-KR-Standard-A",
    },
    "en-US": {
        "neural2": "en-US-Neural2-F",
        "wavenet": "en-US-Wavenet-F",
        "standard": "en-US-Standard-F",
    },
}


def speech_language(text: str, fallback: str = "ko") -> str:
    """Recognize Korean/English per utterance; use the fallback for neutral text.

    Korean sentences often contain Latin names, so Hangul takes precedence.
    This is deliberately a ko/en policy, not a general language detector.
    """
    if HANGUL.search(text):
        return "ko-KR"
    if re.search(r"[A-Za-z]", text):
        return "en-US"
    return "en-US" if fallback.lower().startswith("en") else "ko-KR"


def spoken_text(text: str, language: str) -> str:
    """Best-effort spelling for engines without phoneme/SSML support."""
    lang = "ko" if language.startswith("ko") else "en"
    return KNOWN_NAMES.sub(lambda match: NAME_PRONUNCIATIONS[match.group().lower()][lang], text)


def speech_ssml(text: str, voice_name: str) -> str:
    """Escape untrusted text and give names their explicit English pronunciations.

    Korean voices lack the requested English phonemes/stress. Switch only the
    name to a compatible English voice of the same tier in Korean utterances.
    """
    tier = voice_name.split("-")[2].lower()

    def pronounce(match):
        ipa = NAME_PRONUNCIATIONS[match.group().lower()]["ipa"]
        name = f'<phoneme alphabet="ipa" ph="{ipa}">{match.group()}</phoneme>'
        if voice_name.startswith("ko-"):
            name = f'<voice name="{GCP_VOICES["en-US"][tier]}">{name}</voice>'
        return name

    # Match before escaping so literal input markup is always treated as text.
    parts = []
    start = 0
    for match in KNOWN_NAMES.finditer(text):
        parts.extend((escape(text[start:match.start()]), pronounce(match)))
        start = match.end()
    parts.append(escape(text[start:]))
    return "<speak>" + "".join(parts) + "</speak>"
