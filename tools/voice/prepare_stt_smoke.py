#!/usr/bin/env python3
"""Create synthetic Korean/English smoke samples, not production acceptance audio."""
import argparse
import io
import json
from pathlib import Path
import subprocess
import wave

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
RATE = 16000


def synthesize(text, language):
    from gtts import gTTS
    output = io.BytesIO()
    gTTS(text=text, lang=language, timeout=(3, 10)).write_to_fp(output)
    decoded = subprocess.run(
        ['ffmpeg', '-v', 'error', '-i', 'pipe:0', '-ar', str(RATE), '-ac', '1', '-f', 's16le', 'pipe:1'],
        input=output.getvalue(), capture_output=True, check=True,
    )
    return np.frombuffer(decoded.stdout, dtype='<i2')


def trim(pcm):
    active = np.flatnonzero(np.abs(pcm.astype(np.int32)) > 256)
    if not active.size:
        raise ValueError('Synthetic speech is empty')
    start, end = max(0, active[0] - RATE // 5), active[-1] + 1
    return pcm[start:end].copy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / '.state/voice/stt-smoke')
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    phrases = [
        ('ko_short', [('안녕', 'ko')], ['ko'], 0),
        ('ko_question', [('캠퍼스 도서관은 어디에 있나요?', 'ko')], ['ko'], 0),
        ('en_question', [('Where is the campus library?', 'en')], ['en'], 0),
        ('mixed', [('도서관에 가려면', 'ko'), ('should I turn left?', 'en')], ['ko', 'en'], .25),
        ('ko_pause', [('잠시만요', 'ko'), ('도서관은 어디에 있나요?', 'ko')], ['ko'], .35),
    ]
    manifest = []
    for name, parts, languages, pause in phrases:
        chunks = []
        for index, (text, language) in enumerate(parts):
            if index:
                chunks.append(np.zeros(round(pause * RATE), dtype='<i2'))
            chunks.append(trim(synthesize(text, language)))
        pcm = np.concatenate(chunks)
        # This is an energy estimate, not a human-labeled phonetic boundary.
        speech_end = len(pcm) / RATE
        pcm = np.concatenate([pcm, np.zeros(RATE // 5, dtype='<i2')])
        if not .5 <= len(pcm) / RATE <= 10:
            raise ValueError('Generated sample is outside the app audio limit')
        with wave.open(str(args.output_dir / f'{name}.wav'), 'wb') as wav:
            wav.setparams((1, 2, RATE, 0, 'NONE', ''))
            wav.writeframes(pcm.astype('<i2').tobytes())
        manifest.append({'id': name, 'audio': f'{name}.wav',
                         'reference': ' '.join(text for text, _ in parts),
                         'expected_languages': languages, 'speech_end_seconds': speech_end,
                         'source': 'synthetic_energy_labeled'})
    rng = np.random.default_rng(7)
    for name, pcm in [('silence', np.zeros(RATE * 2, dtype='<i2')),
                      ('low_noise', rng.integers(-50, 51, RATE * 2, dtype=np.int16))]:
        with wave.open(str(args.output_dir / f'{name}.wav'), 'wb') as wav:
            wav.setparams((1, 2, RATE, 0, 'NONE', ''))
            wav.writeframes(pcm.astype('<i2').tobytes())
        manifest.append({'id': name, 'audio': f'{name}.wav', 'reference': '', 'source': 'synthetic'})
    path = args.output_dir / 'manifest.json'
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Created {len(manifest)} synthetic smoke samples: {path}')


if __name__ == '__main__':
    main()
