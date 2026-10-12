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
