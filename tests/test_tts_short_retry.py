import asyncio
from pathlib import Path

import pytest
from video import narrator


class RejectedSpeechService(Exception):
    status = 403


def test_short_retries_403_without_partial_audio(monkeypatch, tmp_path):
    audio, srt = tmp_path / 'narration.mp3', tmp_path / 'narration.srt'
    attempts, delays = [], []
    async def synth(text, audio_path, srt_path):
        assert not Path(audio_path).exists()
        assert not Path(srt_path).exists()
        attempts.append(text)
        Path(audio_path).write_bytes(b'partial' if len(attempts) < 3 else b'complete')
        Path(srt_path).write_text('captions')
        if len(attempts) < 3:
            raise RejectedSpeechService('wss://service?secret=private')
        return 1
    async def sleep(delay):
        delays.append(delay)
    monkeypatch.setattr(narrator, '_synthesise_single', synth)
    monkeypatch.setattr(narrator.asyncio, 'sleep', sleep)
    monkeypatch.setattr(narrator.config, 'EDGE_TTS_CHUNK_RETRIES', 3)
    assert asyncio.run(narrator._synthesise('A short narration.', str(audio), str(srt))) == 1
    assert len(attempts) == 3
    assert delays == [2, 4]
    assert audio.read_bytes() == b'complete'


@pytest.mark.parametrize('failure', [RejectedSpeechService, TimeoutError, RuntimeError])
def test_short_permanent_failure_is_bounded_and_redacted(monkeypatch, tmp_path, capsys, failure):
    audio, srt = tmp_path / 'narration.mp3', tmp_path / 'narration.srt'
    calls = []
    async def synth(*args):
        calls.append(1)
        audio.write_bytes(b'partial')
        srt.write_text('partial')
        raise failure('secret_request_token')
    async def sleep(delay):
        pass
    monkeypatch.setattr(narrator, '_synthesise_single', synth)
    monkeypatch.setattr(narrator.asyncio, 'sleep', sleep)
    monkeypatch.setattr(narrator.config, 'EDGE_TTS_CHUNK_RETRIES', 3)
    with pytest.raises(RuntimeError, match='after 3 attempts') as caught:
        asyncio.run(narrator._synthesise('Short text.', str(audio), str(srt)))
    assert len(calls) == 3
    assert not audio.exists() and not srt.exists()
    assert 'secret_request_token' not in str(caught.value) + capsys.readouterr().out


def test_invalid_voice_configuration_is_not_retried(monkeypatch, tmp_path):
    calls = []
    async def synth(*args):
        calls.append(1)
        raise ValueError('Invalid voice')
    monkeypatch.setattr(narrator, '_synthesise_single', synth)
    with pytest.raises(ValueError, match='Invalid voice'):
        asyncio.run(narrator._synthesise('Short text.', str(tmp_path/'n.mp3'), str(tmp_path/'n.srt')))
    assert len(calls) == 1


def test_empty_audio_is_retried(monkeypatch, tmp_path):
    calls = []
    async def synth(text, audio, srt):
        calls.append(1)
        Path(audio).write_bytes(b'' if len(calls) == 1 else b'audio')
        return 1
    async def sleep(delay):
        pass
    monkeypatch.setattr(narrator, '_synthesise_single', synth)
    monkeypatch.setattr(narrator.asyncio, 'sleep', sleep)
    assert asyncio.run(narrator._synthesise('Short text.', str(tmp_path/'n.mp3'), str(tmp_path/'n.srt'))) == 1
    assert len(calls) == 2


def test_exhausted_edge_uses_piper_and_rebuilds_captions(monkeypatch, tmp_path):
    from video import offline_tts
    async def unavailable(*args):
        raise narrator._EdgeTTSUnavailable('HTTP 403')
    calls = []
    def fallback(text, audio_path):
        calls.append(text)
        Path(audio_path).write_bytes(b'local audio')
    monkeypatch.setattr(narrator, '_synthesise', unavailable)
    monkeypatch.setattr(offline_tts, 'synthesise', fallback)
    monkeypatch.setattr(narrator, '_get_audio_duration_ms', lambda _: 3000)
    text = 'This is the complete narration.'
    audio = narrator.generate_narration({'sections':[{'narration':text}]}, str(tmp_path))
    assert calls == [text]
    assert Path(audio).read_bytes() == b'local audio'
    captions = (tmp_path/'narration.srt').read_text()
    assert text in captions
    assert '00:00:03,000' in captions


def test_fallback_failure_removes_partial_outputs(monkeypatch, tmp_path):
    from video import offline_tts
    async def unavailable(*args):
        raise narrator._EdgeTTSUnavailable('HTTP 403')
    def fallback(text, audio_path):
        Path(audio_path).write_bytes(b'partial')
        (tmp_path/'narration.srt').write_text('partial')
        raise RuntimeError('Local voice unavailable')
    monkeypatch.setattr(narrator, '_synthesise', unavailable)
    monkeypatch.setattr(offline_tts, 'synthesise', fallback)
    with pytest.raises(RuntimeError, match='Local voice unavailable'):
        narrator.generate_narration({'sections':[{'narration':'Text.'}]}, str(tmp_path))
    assert not (tmp_path/'narration.mp3').exists()
    assert not (tmp_path/'narration.srt').exists()


def test_missing_model_fails_without_implicit_download(monkeypatch, tmp_path):
    from video import offline_tts
    monkeypatch.setenv('PIPER_MODEL_DIR', str(tmp_path))
    with pytest.raises(RuntimeError, match='model missing or invalid'):
        offline_tts.ensure_model()


def test_corrupt_model_rejected(monkeypatch, tmp_path):
    from video import offline_tts
    monkeypatch.setenv('PIPER_MODEL_DIR', str(tmp_path))
    (tmp_path/offline_tts.MODEL_NAME).write_bytes(b'corrupt')
    with pytest.raises(RuntimeError, match='model missing or invalid'):
        offline_tts.ensure_model()
