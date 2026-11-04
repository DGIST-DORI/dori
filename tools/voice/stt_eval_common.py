"""Common WAV input and scoring for bounded, real-time STT evaluation."""
from dataclasses import dataclass
import json
import math
from pathlib import Path
import unicodedata
import wave

BYTES_PER_SECOND = 32000


class EvaluationError(Exception):
    """Safe error code: never include raw exceptions or authorization headers."""



@dataclass
class Sample:
    name: str
    pcm: bytes
    reference: str
    speech_end_seconds: float | None = None
    expected_languages: tuple = ()
    source: str = 'recorded'

    @property
    def seconds(self):
        return len(self.pcm) / BYTES_PER_SECOND



def load_manifest(path):
    path = Path(path)
    entries = json.loads(path.read_text())
    if not isinstance(entries, list) or not 1 <= len(entries) <= 20:
        raise ValueError('Manifest must contain 1 to 20 samples')
    samples, names = [], set()
    for entry in entries:
        name = entry['id']
        if not isinstance(name, str) or not name or name in names:
            raise ValueError('Sample IDs must be unique nonempty strings')
        names.add(name)
        reference = entry['reference']
        if not isinstance(reference, str):
            raise ValueError('reference must be text; use an empty string for silence')
        with wave.open(str(path.parent / entry['audio']), 'rb') as wav:
            frames = wav.getnframes()
            if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (16000, 1, 2, 'NONE'):
                raise ValueError('Samples must be 16 kHz mono PCM16 WAV')
            if not 8000 <= frames <= 160000:
                raise ValueError('Samples must be 0.5 to 10 seconds, matching the app')
            pcm = wav.readframes(frames)
            if len(pcm) != frames * 2:
                raise ValueError('Truncated WAV')
        end = entry.get('speech_end_seconds')
        if end is not None and (not isinstance(end, (int, float)) or not math.isfinite(end) or not 0 < end <= frames / 16000):
            raise ValueError('speech_end_seconds must fall within the recording')
        languages = entry.get('expected_languages', [])
        if not isinstance(languages, list) or any(not isinstance(lang, str) for lang in languages):
            raise ValueError('expected_languages must be a list of language codes')
        samples.append(Sample(name, pcm, reference, end, tuple(languages), entry.get('source', 'recorded')))
    return samples



def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())



def character_error_rate(reference, actual):
    reference, actual = normalized(reference), normalized(actual)
    if not reference:
        return None  # Silence is measured as a false positive, not CER.
    previous = list(range(len(actual) + 1))
    for i, expected in enumerate(reference, 1):
        current = [i]
        for j, received in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (expected != received)))
        previous = current
    return previous[-1] / len(reference)



def percentile(values, fraction):
    if not values:
        return None
    values = sorted(values)
    index = (len(values) - 1) * fraction
    lower, upper = math.floor(index), math.ceil(index)
    return values[lower] + (values[upper] - values[lower]) * (index - lower)

