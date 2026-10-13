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


def test_later_long_chunk_failure_falls_back_for_complete_text(monkeypatch, tmp_path, capsys):
    from video import offline_tts
    text = ' '.join(f'word{i}' for i in range(170))
    chunks = narrator._split_text_for_tts(text, 80)
    attempts, fallback_texts = [], []

    async def synth(chunk, audio, srt):
        attempts.append(chunk)
        Path(audio).write_bytes(b'partial')
        Path(srt).write_text('partial')
        if chunk != chunks[0]:
            raise RejectedSpeechService('secret_request_token')
        return 1

    async def sleep(delay):
        pass

    def fallback(full_text, audio):
        fallback_texts.append(full_text)
        Path(audio).write_bytes(b'complete male narration')

    monkeypatch.setattr(narrator.config, 'EDGE_TTS_CHUNK_WORDS', 80)
    monkeypatch.setattr(narrator.config, 'EDGE_TTS_CHUNK_RETRIES', 3)
    monkeypatch.setattr(narrator, '_synthesise_single', synth)
    monkeypatch.setattr(narrator.asyncio, 'sleep', sleep)
    monkeypatch.setattr(narrator, '_get_audio_duration_ms', lambda _: 60000)
    monkeypatch.setattr(offline_tts, 'synthesise', fallback)
    audio = narrator.generate_narration({'sections': [{'narration': text}]}, str(tmp_path))
    assert attempts == [chunks[0]] + [chunks[1]] * 3
    assert fallback_texts == [text]
    assert Path(audio).read_bytes() == b'complete male narration'
    captions = narrator._read_srt_blocks(str(tmp_path / 'narration.srt'))
    assert ' '.join(' '.join(lines) for _, _, lines in captions) == text
    assert captions[-1][1] == 60000
    assert not list(tmp_path.glob('edge_tts_chunks_*'))
    assert 'secret_request_token' not in capsys.readouterr().out


def test_invalid_long_voice_configuration_is_not_retried(monkeypatch, tmp_path):
    calls = []

    async def synth(text, audio, srt):
        calls.append(text)
        Path(audio).write_bytes(b'partial')
        raise ValueError('Invalid voice')

    monkeypatch.setattr(narrator.config, 'EDGE_TTS_CHUNK_WORDS', 80)
    monkeypatch.setattr(narrator, '_synthesise_single', synth)
    with pytest.raises(ValueError, match='Invalid voice'):
        asyncio.run(narrator._synthesise('word ' * 170, str(tmp_path/'n.mp3'), str(tmp_path/'n.srt')))
    assert len(calls) == 1
    assert not list(tmp_path.iterdir())


def test_model_download_verifies_assets_and_reuses_cache(monkeypatch, tmp_path):
    import hashlib
    import io
    from video import offline_tts
    assets = {name: f'asset {name}'.encode() for name in offline_tts.MODEL_FILES}
    downloads = []

    def download(url, timeout):
        # The model filename, directory and companion assets must agree.
        base, name = url.rsplit('/', 1)
        assert base.endswith('/en/en_US/john/medium')
        assert offline_tts.MODEL_NAME == 'en_US-john-medium.onnx'
        downloads.append(name)
        return io.BytesIO(assets[name])

    monkeypatch.setenv('PIPER_MODEL_DIR', str(tmp_path))
    monkeypatch.setattr(offline_tts, 'MODEL_FILES', {
        name: hashlib.sha256(data).hexdigest() for name, data in assets.items()
    })
    monkeypatch.setattr(offline_tts, 'urlopen', download)
    model = offline_tts.ensure_model(download=True)
    assert model.read_bytes() == assets[offline_tts.MODEL_NAME]
    assert offline_tts.ensure_model() == model
    assert downloads == list(assets)


def test_bad_download_never_replaces_verified_model(monkeypatch, tmp_path):
    import io
    from video import offline_tts
    monkeypatch.setenv('PIPER_MODEL_DIR', str(tmp_path))
    monkeypatch.setattr(offline_tts, 'urlopen', lambda *a, **k: io.BytesIO(b'wrong model'))
    monkeypatch.setattr(offline_tts.time, 'sleep', lambda _: None)
    with pytest.raises(RuntimeError, match='Could not provision verified Piper asset'):
        offline_tts.ensure_model(download=True)
    assert not list(tmp_path.iterdir())
