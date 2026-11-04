#!/usr/bin/env python3
"""Evaluate Azure Speech F0 with paced PCM input and at-start language detection.

Independent of the running app. No resource creation, tier upgrades or paid
continuous language identification. --dry-run makes no network requests.
"""
import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shlex
import sys
import threading
import time
import wave

from stt_eval_common import (
    BYTES_PER_SECOND, EvaluationError, character_error_rate,
    load_manifest, normalized, percentile,
)

ROOT = Path(__file__).resolve().parents[2]
MAX_RUN_AUDIO_SECONDS = 120


@dataclass(frozen=True)
class AzureSettings:
    key: str = field(repr=False)
    region: str
    tier: str


def load_settings(path):
    names = ('AZURE_SPEECH_KEY', 'AZURE_SPEECH_REGION', 'AZURE_SPEECH_TIER')
    values = {}
    if Path(path).is_file():
        for line in Path(path).read_text().splitlines():
            name, separator, value = line.strip().removeprefix('export ').partition('=')
            if separator and name.strip() in names:
                parts = shlex.split(value, comments=True)
                if len(parts) > 1:
                    raise EvaluationError('invalid_settings')
                values[name.strip()] = parts[0] if parts else ''
    for name in names:
        if os.environ.get(name, '').strip():
            values[name] = os.environ[name].strip()
    if values.get('AZURE_SPEECH_TIER') != 'F0':
        raise EvaluationError('f0_confirmation_required')
    key, region = values.get('AZURE_SPEECH_KEY', ''), values.get('AZURE_SPEECH_REGION', '')
    if not key or not region:
        raise EvaluationError('missing_azure_key_or_region')
    if any(char.isspace() for char in key) or not re.fullmatch(r'[a-z][a-z0-9]{1,39}', region):
        raise EvaluationError('invalid_settings')
    return AzureSettings(key, region, 'F0')


def validate_languages(languages):
    if not 1 <= len(languages) <= 4 or any(not re.fullmatch(r'[a-z]{2,3}-[A-Z]{2}', lang) for lang in languages):
        raise ValueError('At-start LID needs 1 to 4 locale codes, for example ko-KR en-US')
    if len({lang.split('-')[0] for lang in languages}) != len(languages):
        raise ValueError('Use only one locale per base language')


def create_recognizer(sdk, settings, languages, silence_ms):
    if settings.tier != 'F0':
        raise EvaluationError('f0_confirmation_required')
    validate_languages(languages)
    if not 100 <= silence_ms <= 2000:
        raise ValueError('silence_ms must be 100 to 2000')
    config = sdk.SpeechConfig(subscription=settings.key, region=settings.region)
    config.set_property(sdk.PropertyId.SpeechServiceConnection_LanguageIdMode, 'AtStart')
    config.set_property(sdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, str(silence_ms))
    config.set_property(sdk.PropertyId.SpeechServiceConnection_InitialSilenceTimeoutMs, '5000')
    config.set_property(sdk.PropertyId.SpeechServiceConnection_EnableAudioLogging, 'false')
    stream = sdk.audio.PushAudioInputStream(stream_format=sdk.audio.AudioStreamFormat(
        samples_per_second=16000, bits_per_sample=16, channels=1))
    recognizer = sdk.SpeechRecognizer(
        speech_config=config, audio_config=sdk.audio.AudioConfig(stream=stream),
        auto_detect_source_language_config=sdk.languageconfig.AutoDetectSourceLanguageConfig(languages=languages),
    )
    return recognizer, stream


class Transcript:
    """Called under a lock because the SDK invokes callbacks from native threads."""
    def __init__(self):
        self.segments = {}
        self.finals = []
        self.first_text_ms = None
        self.session_started_ms = None
        self.no_match_count = 0
        self.error = None
        self.flushing = False
        self.input_closed_ms = None

    @property
    def text(self):
        return ' '.join(self.segments[key]['text'] for key in sorted(self.segments)).strip()

    def add(self, text, at_ms, *, final=False, offset=0, duration=0, language=''):
        text = text.strip()
        if not text:
            return
        if self.first_text_ms is None:
            self.first_text_ms = at_ms
        if not final:
            return
        self.segments[(offset, duration)] = {'text': text, 'language': language}
        self.finals.append({'at_ms': at_ms, 'text': self.text, 'forced': self.flushing,
                            'audio_end_seconds': (offset + duration) / 10000000})

    def report(self, sample, audio_started_ms, speech_end_ms, file_end_ms):
        natural = [event for event in self.finals if not event['forced']]
        completed = [event for event in self.finals if normalized(event['text']) == normalized(self.text)
                     and (speech_end_ms is None or event['at_ms'] >= speech_end_ms)]
        complete = [event for event in completed if not event['forced']]
        final = complete[0] if complete else None
        ready = completed[0] if completed else None
        latency = final['at_ms'] - speech_end_ms if final and speech_end_ms is not None else None
        ready_latency = ready['at_ms'] - speech_end_ms if ready and speech_end_ms is not None else None
        languages = sorted({s['language'] for s in self.segments.values() if s['language']})
        detected = {lang.split('-')[0].lower() for lang in languages}
        expected = {lang.split('-')[0].lower() for lang in sample.expected_languages}
        return {
            'id': sample.name, 'source': sample.source, 'reference': sample.reference,
            'audio_seconds': sample.seconds, 'transcript': self.text,
            'languages': languages, 'language_match': expected <= detected if expected else None,
            'cer': character_error_rate(sample.reference, self.text),
            'silence_false_positive': bool(self.text) if not sample.reference.strip() else None,
            'session_started_ms': self.session_started_ms,
            'first_text_ms': self.first_text_ms - audio_started_ms if self.first_text_ms is not None else None,
            'speech_end_to_final_ms': latency,
            'speech_end_to_text_ms': ready_latency,
            'text_within_1500ms': ready_latency <= 1500 if ready_latency is not None else None,
            'completion_trigger': ('input_close' if ready['forced'] else 'natural') if ready else None,
            'input_close_to_text_ms': ready['at_ms'] - self.input_closed_ms
                if ready and ready['forced'] and self.input_closed_ms is not None else None,
            'speech_end_to_input_close_ms': self.input_closed_ms - speech_end_ms
                if self.input_closed_ms is not None and speech_end_ms is not None else None,
            'file_end_to_final_ms': final['at_ms'] - file_end_ms if final and file_end_ms is not None else None,
            'final_within_1500ms': latency <= 1500 if latency is not None else None,
            'natural_final_missing': bool(sample.reference.strip()) and not complete,
            'premature_final_count': sum(e['at_ms'] < speech_end_ms for e in natural) if speech_end_ms is not None else None,
            'no_match_count': self.no_match_count, 'finals': self.finals,
            'error': self.error,
        }


def stream_sample(sample, settings, *, languages=('ko-KR', 'en-US'), silence_ms=500,
                  chunk_ms=100, tail_ms=5000, endpoint_mode='azure', drain_timeout=8, sdk=None,
                  clock=time.monotonic, wait=None):
    if not 20 <= chunk_ms <= 250 or not 100 <= tail_ms <= 5000:
        raise ValueError('Use 20–250 ms chunks and 100–5000 ms trailing silence')
    if endpoint_mode not in ('azure', 'input-close'):
        raise ValueError('endpoint_mode must be azure or input-close')
    if sdk is None:
        try:
            import azure.cognitiveservices.speech as sdk
        except ImportError as exc:
            raise EvaluationError('azure_sdk_not_installed') from exc
    started = clock()
    transcript, lock, done = Transcript(), threading.Lock(), threading.Event()
    stop_input = threading.Event()
    pause = wait or stop_input.wait
    try:
        recognizer, stream = create_recognizer(sdk, settings, languages, silence_ms)
    except (EvaluationError, ValueError):
        raise
    except Exception as exc:
        raise EvaluationError('azure_setup_error') from exc
    callbacks_enabled = True
    audio_started_ms = 0
    speech_end_ms = file_end_ms = None
    max_send_lag_ms = 0
    bytes_sent = 0
    azure_endpoint_ms = None
    close_reason = 'input_limit'
    signals = []

    def callback(function):
        def guarded(event):
            at_ms = (clock() - started) * 1000
            with lock:
                if not callbacks_enabled:
                    return
                try:
                    function(event, at_ms)
                except Exception:
                    transcript.error = 'callback_error'
                    done.set()
                    stop_input.set()
        return guarded

    def recognizing(event, at_ms):
        transcript.add(event.result.text, at_ms)

    def recognized(event, at_ms):
        nonlocal azure_endpoint_ms, close_reason
        result = event.result
        if result.reason == sdk.ResultReason.RecognizedSpeech:
            language = sdk.AutoDetectSourceLanguageResult(result).language
            transcript.add(result.text, at_ms, final=True, offset=result.offset,
                           duration=result.duration, language=language)
            if endpoint_mode == 'azure' and result.text.strip() and not transcript.flushing and azure_endpoint_ms is None:
                azure_endpoint_ms = at_ms
                close_reason = 'azure_final'
                stop_input.set()
        elif result.reason == sdk.ResultReason.NoMatch:
            transcript.no_match_count += 1
            if endpoint_mode == 'azure' and not transcript.flushing and azure_endpoint_ms is None:
                close_reason = 'azure_no_match'
                stop_input.set()

    def session_started(_event, at_ms):
        transcript.session_started_ms = at_ms

    def session_stopped(_event, _at_ms):
        if not transcript.flushing and not transcript.error:
            transcript.error = 'session_stopped_early'
        done.set()
        stop_input.set()

    def canceled(event, _at_ms):
        details = event.cancellation_details
        if details.reason == sdk.CancellationReason.Error:
            code = getattr(details.code, 'name', 'unknown')
            # Never include provider error_details: it can contain request data.
            transcript.error = 'azure_' + (code if re.fullmatch(r'[A-Za-z0-9_]+', code) else 'unknown')
        elif not transcript.flushing:
            transcript.error = 'session_canceled_early'
        done.set()
        stop_input.set()

    for name, handler in (('recognizing', recognizing), ('recognized', recognized),
                          ('session_started', session_started), ('session_stopped', session_stopped),
                          ('canceled', canceled)):
        signal = getattr(recognizer, name)
        signal.connect(callback(handler))
        signals.append(signal)
    try:
        recognizer.start_continuous_recognition_async().get()
        audio_started = clock()
        audio_started_ms = (audio_started - started) * 1000
        audio = sample.pcm + bytes(tail_ms * BYTES_PER_SECOND // 1000)
        chunk_bytes = chunk_ms * BYTES_PER_SECOND // 1000
        for offset in range(0, len(audio), chunk_bytes):
            end = min(offset + chunk_bytes, len(audio))
            due = audio_started + end / BYTES_PER_SECOND
            if pause(max(0, due - clock())) or stop_input.is_set() or done.is_set():
                break
            stream.write(audio[offset:end])
            bytes_sent = end
            now = clock()
            elapsed = (now - started) * 1000
            max_send_lag_ms = max(max_send_lag_ms, (now - due) * 1000)
            if file_end_ms is None and end >= len(sample.pcm):
                file_end_ms = elapsed - (end - len(sample.pcm)) / BYTES_PER_SECOND * 1000
            if sample.speech_end_seconds is not None and speech_end_ms is None and end / BYTES_PER_SECOND >= sample.speech_end_seconds:
                speech_end_ms = elapsed - (end / BYTES_PER_SECOND - sample.speech_end_seconds) * 1000
        with lock:
            transcript.flushing = True
            transcript.input_closed_ms = (clock() - started) * 1000
        stream.close()
        if not done.wait(drain_timeout):
            with lock:
                transcript.error = 'result_timeout'
    except Exception as exc:
        raise EvaluationError('azure_runtime_error') from exc
    finally:
        with lock:
            callbacks_enabled = False
        try:
            stream.close()
            for signal in signals:
                signal.disconnect_all()
            recognizer.stop_continuous_recognition_async().get()
        except Exception as exc:
            raise EvaluationError('azure_cleanup_error') from exc
    report = transcript.report(sample, audio_started_ms, speech_end_ms, file_end_ms)
    report.update(max_send_lag_ms=max_send_lag_ms, sdk_version=getattr(sdk, '__version__', 'test'),
                  endpoint_mode=endpoint_mode, input_close_reason=close_reason,
                  azure_endpoint_ms=azure_endpoint_ms,
                  transmitted_audio_seconds=bytes_sent / BYTES_PER_SECOND,
                  source_audio_complete=bytes_sent >= len(sample.pcm),
                  speech_truncated=bytes_sent / BYTES_PER_SECOND < sample.speech_end_seconds
                      if sample.speech_end_seconds is not None else None)
    return report


def summarize(results):
    valid = [r for r in results if not r.get('error')]
    latencies = [r['speech_end_to_final_ms'] for r in valid if r['speech_end_to_final_ms'] is not None]
    ready_latencies = [r['speech_end_to_text_ms'] for r in valid if r.get('speech_end_to_text_ms') is not None]
    return {
        'requests': len(results), 'errors': len(results) - len(valid),
        'latency_samples': len(latencies), 'latency_p50_ms': percentile(latencies, .5),
        'latency_p95_ms': percentile(latencies, .95),
        'text_latency_samples': len(ready_latencies),
        'text_latency_p50_ms': percentile(ready_latencies, .5),
        'text_latency_p95_ms': percentile(ready_latencies, .95),
        'input_close_completions': sum(r.get('completion_trigger') == 'input_close' for r in valid),
        'text_missing': sum(bool(r.get('reference', '').strip()) and not r.get('transcript') for r in valid),
        'natural_final_missing': sum(r['natural_final_missing'] for r in valid),
        'silence_false_positives': sum(r['silence_false_positive'] is True for r in valid),
        'language_mismatches': sum(r['language_match'] is False for r in valid),
        'speech_truncations': sum(r.get('speech_truncated') is True for r in valid),
        'azure_endpoint_timeouts': sum(r.get('endpoint_mode') == 'azure'
            and r.get('input_close_reason') == 'input_limit' for r in valid),
        'note': 'latency measures natural finals only; text_latency also includes input-close flushes. Percentiles exclude missing text and unlabeled speech ends and do not imply accurate transcripts. Synthetic samples are smoke tests; inspect failures and premature finals separately.',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--env-file', type=Path, default=ROOT / '.state/voice/azure.env')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--languages', nargs='+', default=['ko-KR', 'en-US'])
    parser.add_argument('--repeats', type=int, choices=range(1, 6), default=1)
    parser.add_argument('--silence-ms', type=int, default=500)
    parser.add_argument('--chunk-ms', type=int, default=100)
    parser.add_argument('--tail-ms', type=int, default=5000)
    parser.add_argument('--endpoint-mode', choices=('azure', 'input-close'), default='azure',
                        help='Stop sending on Azure final/NoMatch (default); input-close replays the full input for diagnostics')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    try:
        samples = load_manifest(args.manifest)
        validate_languages(args.languages)
        if not 100 <= args.silence_ms <= 2000 or not 20 <= args.chunk_ms <= 250 or not 100 <= args.tail_ms <= 5000:
            raise ValueError('Timing parameters are out of range')
        seconds = sum(s.seconds + args.tail_ms / 1000 for s in samples) * args.repeats
        if seconds > MAX_RUN_AUDIO_SECONDS:
            raise EvaluationError('run_exceeds_120_second_audio_budget')
        configuration = {'provider': 'azure_speech', 'required_tier': 'F0', 'lid_mode': 'AtStart',
                         'languages': args.languages, 'silence_ms': args.silence_ms,
                         'chunk_ms': args.chunk_ms, 'tail_ms': args.tail_ms,
                         'endpoint_mode': args.endpoint_mode,
                         'repeats': args.repeats, 'audio_seconds': seconds}
        print(json.dumps({'configuration': configuration}), flush=True)
        if args.dry_run:
            return 0
        settings = load_settings(args.env_file)
        results = []
        for repetition in range(1, args.repeats + 1):
            for sample in samples:
                try:
                    result = stream_sample(sample, settings, languages=args.languages,
                        silence_ms=args.silence_ms, chunk_ms=args.chunk_ms, tail_ms=args.tail_ms,
                        endpoint_mode=args.endpoint_mode)
                except EvaluationError as exc:
                    result = {'id': sample.name, 'error': str(exc)}
                result['repetition'] = repetition
                results.append(result)
                print(json.dumps(result, ensure_ascii=False), flush=True)
                if result.get('error'):
                    break
            if results[-1].get('error'):
                break  # No retry loops, tier upgrades or fallback paid endpoints.
        report = {'created_at': datetime.now(timezone.utc).isoformat(), 'configuration': configuration,
                  'results': results, 'summary': summarize(results)}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
        print(json.dumps({'summary': report['summary']}, ensure_ascii=False), flush=True)
        return 1 if report['summary']['errors'] else 0
    except EvaluationError as exc:
        print(f'Evaluation unavailable: {exc}. Check the F0 resource and local Azure settings.', file=sys.stderr)
        return 2
    except (ValueError, KeyError, TypeError, OSError, wave.Error, EOFError) as exc:
        print(f'Invalid evaluation input ({type(exc).__name__}); check the settings, manifest and WAVs.', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
