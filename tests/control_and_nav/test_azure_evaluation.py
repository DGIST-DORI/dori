"""Azure evaluator tests without credentials, network traffic or ROS nodes."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace as NS
from unittest import TestCase
from unittest.mock import patch
import wave

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools/voice'))
spec = importlib.util.spec_from_file_location('azure_evaluation_under_test', ROOT / 'tools/voice/evaluate_azure.py')
evaluation = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = evaluation
spec.loader.exec_module(evaluation)
from stt_eval_common import Sample, character_error_rate, load_manifest


class Signal:
    def __init__(self):
        self.handlers = []

    def connect(self, handler):
        self.handlers.append(handler)

    def disconnect_all(self):
        self.handlers.clear()

    def emit(self, event=None):
        for handler in self.handlers[:]:
            handler(event)


class FakeClock:
    def __init__(self):
        self.now = 0

    def __call__(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds
        return False


class FakeSDK:
    __version__ = 'test'
    PropertyId = NS(SpeechServiceConnection_LanguageIdMode='lid', Speech_SegmentationSilenceTimeoutMs='silence',
                    SpeechServiceConnection_InitialSilenceTimeoutMs='initial', SpeechServiceConnection_EnableAudioLogging='logging')
    ResultReason = NS(RecognizedSpeech='recognized', NoMatch='no_match')
    CancellationReason = NS(Error='error')

    def __init__(self, clock, *, forced=False, auth_error=False, timeout=False):
        self.clock, self.forced, self.auth_error, self.timeout = clock, forced, auth_error, timeout
        self.properties, self.writes, self.stop_count, self.closed = {}, [], 0, False
        self.audio = NS(AudioStreamFormat=lambda **kwargs: kwargs, PushAudioInputStream=lambda **kwargs: self,
                        AudioConfig=lambda **kwargs: kwargs)
        self.languageconfig = NS(AutoDetectSourceLanguageConfig=lambda **kwargs: kwargs)
        for name in ('recognizing', 'recognized', 'session_started', 'session_stopped', 'canceled'):
            setattr(self, name, Signal())

    def SpeechConfig(self, **kwargs):
        self.configuration = kwargs
        return NS(set_property=self.properties.__setitem__)

    def SpeechRecognizer(self, **kwargs):
        self.recognizer_configuration = kwargs
        return self

    def AutoDetectSourceLanguageResult(self, result):
        return NS(language=result.language)

    def start_continuous_recognition_async(self):
        def start():
            self.clock.now += .05
            self.session_started.emit()
        return NS(get=start)

    def stop_continuous_recognition_async(self):
        def stop():
            self.stop_count += 1
        return NS(get=stop)

    def final(self):
        # SDK events may originate on a native worker thread.
        event = NS(result=NS(text='안녕', reason='recognized', offset=0, duration=4000000, language='ko-KR'))
        worker = threading.Thread(target=self.recognized.emit, args=(event,))
        worker.start()
        worker.join()

    def write(self, data):
        self.writes.append((self.clock(), data))
        count = sum(len(chunk) for _, chunk in self.writes)
        if self.auth_error:
            self.canceled.emit(NS(cancellation_details=NS(
                reason='error', code=NS(name='AuthenticationFailure'), error_details='private-key')))
        elif count == 6400:
            self.recognizing.emit(NS(result=NS(text='아녕')))
        elif count == 32000 and not self.forced:
            self.final()

    def close(self):
        if self.closed:
            return
        self.closed = True
        if self.forced:
            self.final()
        if not self.timeout:
            self.canceled.emit(NS(cancellation_details=NS(reason='end_of_stream')))
            self.session_stopped.emit()


class AzureStreamingTests(TestCase):
    def run_sample(self, endpoint_mode='input-close', **options):
        clock = FakeClock()
        sdk = FakeSDK(clock, **options)
        sample = Sample('short', b'\x01\x00' * 8000, '안녕', .4, ('ko',))
        result = evaluation.stream_sample(sample, evaluation.AzureSettings('private-key', 'koreacentral', 'F0'),
            sdk=sdk, clock=clock, wait=clock.wait, tail_ms=1000, drain_timeout=.001,
            endpoint_mode=endpoint_mode)
        self.assertTrue(sdk.closed)
        self.assertEqual(sdk.stop_count, 1)
        for name in ('recognizing', 'recognized', 'session_started', 'session_stopped', 'canceled'):
            self.assertFalse(getattr(sdk, name).handlers)
        return result, sdk

    def test_paces_raw_audio_and_collects_final_text_from_worker_thread(self):
        result, sdk = self.run_sample()
        self.assertEqual(b''.join(data for _, data in sdk.writes), b'\x01\x00' * 8000 + bytes(32000))
        self.assertAlmostEqual(sdk.writes[0][0], .15)
        self.assertAlmostEqual(sdk.writes[-1][0], 1.55)
        self.assertEqual(result['transcript'], '안녕')
        self.assertAlmostEqual(result['speech_end_to_final_ms'], 600)
        self.assertEqual(result['speech_end_to_text_ms'], result['speech_end_to_final_ms'])
        self.assertEqual(result['completion_trigger'], 'natural')
        self.assertEqual(result['session_started_ms'], 50)
        self.assertTrue(result['language_match'])
        self.assertEqual(result['cer'], 0)
        self.assertIsNone(result['error'])
        self.assertNotIn('private-key', json.dumps(result))
        self.assertEqual(sdk.properties, {'lid': 'AtStart', 'silence': '500', 'initial': '5000', 'logging': 'false'})
        self.assertEqual(sdk.recognizer_configuration['auto_detect_source_language_config']['languages'], ('ko-KR', 'en-US'))

    def test_flush_results_do_not_claim_natural_endpoint_success(self):
        result, _ = self.run_sample(forced=True)
        self.assertEqual(result['transcript'], '안녕')
        self.assertIsNone(result['speech_end_to_final_ms'])
        self.assertTrue(result['natural_final_missing'])
        self.assertIsNone(result['error'])
        self.assertAlmostEqual(result['speech_end_to_text_ms'], 1100)
        self.assertEqual(result['completion_trigger'], 'input_close')
        self.assertEqual(result['input_close_to_text_ms'], 0)
        self.assertAlmostEqual(result['speech_end_to_input_close_ms'], 1100)
        summary = evaluation.summarize([result])
        self.assertEqual(summary['latency_samples'], 0)
        self.assertEqual(summary['text_latency_samples'], 1)
        self.assertEqual(summary['input_close_completions'], 1)

    def test_azure_final_stops_input_without_waiting_for_the_tail(self):
        result, sdk = self.run_sample(endpoint_mode='azure')
        self.assertEqual(sum(len(data) for _, data in sdk.writes), 32000)
        self.assertEqual(result['input_close_reason'], 'azure_final')
        self.assertEqual(result['transmitted_audio_seconds'], 1)
        self.assertEqual(result['completion_trigger'], 'natural')
        self.assertFalse(result['speech_truncated'])
        self.assertIsNone(result['error'])

    def test_azure_endpoint_before_resumed_speech_is_reported_as_truncation(self):
        clock = FakeClock()
        sdk = FakeSDK(clock)
        result = evaluation.stream_sample(Sample('pause', bytes(96000), '안녕 다시 말할게', 2.8),
            evaluation.AzureSettings('key', 'koreacentral', 'F0'), sdk=sdk,
            clock=clock, wait=clock.wait, drain_timeout=.001)
        self.assertEqual(result['endpoint_mode'], 'azure')
        self.assertEqual(result['input_close_reason'], 'azure_final')
        self.assertFalse(result['source_audio_complete'])
        self.assertTrue(result['speech_truncated'])
        self.assertIsNone(result['speech_end_to_text_ms'])
        self.assertEqual(evaluation.summarize([result])['speech_truncations'], 1)

    def test_forced_input_limit_is_not_an_azure_endpoint(self):
        result, _ = self.run_sample(endpoint_mode='azure', forced=True)
        self.assertEqual(result['input_close_reason'], 'input_limit')
        self.assertEqual(evaluation.summarize([result])['azure_endpoint_timeouts'], 1)
        self.assertTrue(result['natural_final_missing'])

    def test_azure_no_match_stops_silent_input_without_inventing_text(self):
        clock = FakeClock()
        sdk = FakeSDK(clock)
        def write(data):
            sdk.writes.append((clock(), data))
            if len(sdk.writes) == 10:
                sdk.recognized.emit(NS(result=NS(reason='no_match')))
        sdk.write = write
        result = evaluation.stream_sample(Sample('silence', bytes(64000), ''),
            evaluation.AzureSettings('key', 'koreacentral', 'F0'), sdk=sdk,
            clock=clock, wait=clock.wait, drain_timeout=.001)
        self.assertEqual(result['input_close_reason'], 'azure_no_match')
        self.assertEqual(result['transmitted_audio_seconds'], 1)
        self.assertEqual(result['transcript'], '')
        self.assertFalse(result['silence_false_positive'])
        self.assertIsNone(result['error'])

    def test_short_tail_models_client_endpoint_without_claiming_natural_final(self):
        clock = FakeClock()
        sdk = FakeSDK(clock, forced=True)
        result = evaluation.stream_sample(Sample('short', bytes(32000), '안녕', .8),
            evaluation.AzureSettings('key', 'koreacentral', 'F0'), sdk=sdk,
            clock=clock, wait=clock.wait, tail_ms=600, drain_timeout=.001)
        self.assertAlmostEqual(result['speech_end_to_input_close_ms'], 800)
        self.assertAlmostEqual(result['speech_end_to_text_ms'], 800)
        self.assertIsNone(result['speech_end_to_final_ms'])
        self.assertIsNone(result['error'])

    def test_auth_failure_stops_audio_without_retry_or_provider_details(self):
        result, sdk = self.run_sample(auth_error=True)
        self.assertEqual(result['error'], 'azure_AuthenticationFailure')
        self.assertEqual(len(sdk.writes), 1)
        self.assertNotIn('private-key', json.dumps(result))

    def test_missing_session_stop_is_a_bounded_failure(self):
        result, _ = self.run_sample(timeout=True)
        self.assertEqual(result['error'], 'result_timeout')

    def test_paid_tier_is_rejected_before_sdk_configuration(self):
        sdk = FakeSDK(FakeClock())
        with self.assertRaisesRegex(evaluation.EvaluationError, 'f0_confirmation_required'):
            evaluation.create_recognizer(sdk, evaluation.AzureSettings('key', 'koreacentral', 'S0'), ['ko-KR', 'en-US'], 500)
        self.assertFalse(hasattr(sdk, 'configuration'))


class MetricTests(TestCase):
    def test_partial_revisions_and_early_finals_are_not_full_sentence_latency(self):
        transcript = evaluation.Transcript()
        transcript.add('틀린 말', 100)
        transcript.add('잠시만요', 900, final=True, duration=8000000, language='ko-KR')
        transcript.add('도서관은 어디인가요', 3800, final=True, offset=10000000, duration=20000000, language='ko-KR')
        sample = Sample('pause', bytes(96000), '잠시만요 도서관은 어디인가요', 2.8, ('ko',))
        report = transcript.report(sample, 0, 2800, 3000)
        self.assertEqual(report['speech_end_to_final_ms'], 1000)
        self.assertEqual(report['premature_final_count'], 1)
        self.assertEqual(report['cer'], 0)

    def test_late_flushed_suffix_invalidates_earlier_final(self):
        transcript = evaluation.Transcript()
        transcript.add('도서관', 1200, final=True, duration=10000000)
        transcript.flushing = True
        transcript.add('어디야', 3000, final=True, offset=10000000, duration=5000000)
        report = transcript.report(Sample('question', bytes(64000), '도서관 어디야', 1.5), 0, 1500, 2000)
        self.assertTrue(report['natural_final_missing'])
        self.assertIsNone(report['speech_end_to_final_ms'])

    def test_unlabeled_ends_and_silence_have_no_invented_latency(self):
        transcript = evaluation.Transcript()
        transcript.add('안녕', 1500, final=True, duration=10000000, language='ko-KR')
        sample = Sample('unlabeled', bytes(32000), '안녕')
        report = transcript.report(sample, 0, None, 1000)
        self.assertIsNone(report['speech_end_to_final_ms'])
        self.assertEqual(report['file_end_to_final_ms'], 500)
        silence = transcript.report(Sample('silence', bytes(32000), ''), 0, None, 1000)
        summary = evaluation.summarize([report, silence, {'error': 'timeout'}])
        self.assertEqual(summary['latency_samples'], 0)
        self.assertEqual(summary['silence_false_positives'], 1)
        self.assertEqual(summary['errors'], 1)

    def test_mixed_language_limit_is_visible_in_report(self):
        transcript = evaluation.Transcript()
        transcript.add('안녕 hello', 1500, final=True, duration=10000000, language='ko-KR')
        report = transcript.report(Sample('mixed', bytes(32000), '안녕 hello', expected_languages=('ko', 'en')), 0, None, 1000)
        self.assertFalse(report['language_match'])


class InputTests(TestCase):
    def test_config_requires_explicit_f0_and_keeps_key_out_of_repr(self):
        environment = {name: '' for name in ('AZURE_SPEECH_KEY', 'AZURE_SPEECH_REGION', 'AZURE_SPEECH_TIER')}
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, environment):
            path = Path(temporary) / 'azure.env'
            path.write_text('AZURE_SPEECH_KEY=private-key\nAZURE_SPEECH_REGION=koreacentral\n')
            with self.assertRaisesRegex(evaluation.EvaluationError, 'f0_confirmation_required'):
                evaluation.load_settings(path)
            with path.open('a') as config:
                config.write('AZURE_SPEECH_TIER=F0\n')
            settings = evaluation.load_settings(path)
            self.assertEqual(settings.key, 'private-key')
            self.assertNotIn('private-key', repr(settings))
            with patch.dict(os.environ, {'AZURE_SPEECH_TIER': 'S0'}):
                with self.assertRaisesRegex(evaluation.EvaluationError, 'f0_confirmation_required'):
                    evaluation.load_settings(path)

    def test_language_candidates_reject_duplicates_and_over_four(self):
        evaluation.validate_languages(['ko-KR', 'en-US', 'ja-JP', 'zh-CN'])
        for values in ([], ['en-US', 'en-GB'], ['ko-KR', 'en-US', 'ja-JP', 'zh-CN', 'de-DE'], ['korean']):
            with self.assertRaises(ValueError):
                evaluation.validate_languages(values)

    def test_manifest_validation_dry_run_and_budget_need_no_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            audio, manifest = root / 'sample.wav', root / 'manifest.json'
            with wave.open(str(audio), 'wb') as wav:
                wav.setparams((1, 2, 16000, 0, 'NONE', ''))
                wav.writeframes(bytes(32000))
            entry = {'id': 'sample', 'audio': 'sample.wav', 'reference': '안녕', 'speech_end_seconds': .5}
            manifest.write_text(json.dumps([entry]))
            self.assertEqual(load_manifest(manifest)[0].seconds, 1)
            with patch('sys.stdout', new_callable=io.StringIO), patch.object(evaluation, 'load_settings') as settings:
                self.assertEqual(evaluation.main(['--manifest', str(manifest), '--dry-run']), 0)
                settings.assert_not_called()
            manifest.write_text(json.dumps([{**entry, 'id': str(index)} for index in range(20)]))
            with patch('sys.stderr', new_callable=io.StringIO), patch.object(evaluation, 'load_settings') as settings:
                self.assertEqual(evaluation.main(['--manifest', str(manifest), '--repeats', '5']), 2)
                settings.assert_not_called()
            manifest.write_text(json.dumps([{**entry, 'speech_end_seconds': 2}]))
            with self.assertRaises(ValueError):
                load_manifest(manifest)

    def test_character_error_metric_normalizes_punctuation_and_spacing(self):
        self.assertEqual(character_error_rate('안녕하세요 DGIST!', '안녕 하세요 dgist'), 0)
        self.assertEqual(character_error_rate('hello', 'hallo'), .2)
