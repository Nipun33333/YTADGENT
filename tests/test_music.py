from array import array
import math
from pathlib import Path
import shutil
import subprocess
import sys
import wave

import pytest
from video import music


def test_theme_is_always_selected_even_with_other_tracks(tmp_path):
    for name in ('another.mp3', music.BACKGROUND_TRACK, 'other.wav'):
        (tmp_path/name).write_bytes(b'track')
    for _ in range(5):
        assert music._get_library_tracks(str(tmp_path)) == [str(tmp_path/music.BACKGROUND_TRACK)]


@pytest.mark.parametrize('volume,has_track', [(0, True), (.15, False)])
def test_disabled_or_missing_music_preserves_narration(tmp_path, volume, has_track):
    source, output = tmp_path/'voice.bin', tmp_path/'mix.mp3'
    source.write_bytes(b'original voice')
    if has_track:
        (tmp_path/music.BACKGROUND_TRACK).write_bytes(b'track')
    music.mix_music_with_narration(str(source), str(output), volume, str(tmp_path))
    assert output.read_bytes() == source.read_bytes() == b'original voice'


def test_encoder_failure_preserves_source_and_replaces_partial_mix(monkeypatch, tmp_path):
    source, output = tmp_path/'voice.bin', tmp_path/'mix.mp3'
    source.write_bytes(b'original voice')
    (tmp_path/music.BACKGROUND_TRACK).write_bytes(b'track')

    def run(command, **kwargs):
        if command[0] == 'ffprobe':
            return subprocess.CompletedProcess(command, 0, stdout='3.2')
        output.write_bytes(b'partial')
        raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(music.subprocess, 'run', run)
    music.mix_music_with_narration(str(source), str(output), .15, str(tmp_path))
    assert output.read_bytes() == source.read_bytes() == b'original voice'


@pytest.mark.skipif(not shutil.which('ffmpeg') or not shutil.which('ffprobe'), reason='FFmpeg required')
def test_real_mix_loops_music_at_fifteen_percent_without_reducing_voice(tmp_path):
    rate = 44100

    def tone(path, frequency, duration):
        samples = array('h', (int(32767*.2*math.sin(2*math.pi*frequency*i/rate))
                              for i in range(int(duration*rate))))
        if sys.byteorder != 'little':
            samples.byteswap()
        with wave.open(str(path), 'wb') as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(rate)
            out.writeframes(samples.tobytes())

    source, track, output = tmp_path/'voice.wav', tmp_path/'bed.wav', tmp_path/'mix.mp3'
    tone(source, 440, 3.2)
    tone(track, 220, .4)
    original = source.read_bytes()
    music.mix_music_with_narration(str(source), str(output), .15, str(tmp_path))
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-ar', str(rate),
                              '-ac', '1', '-f', 'f32le', 'pipe:1'],
                             capture_output=True, check=True).stdout
    samples = array('f')
    samples.frombytes(decoded)
    if sys.byteorder != 'little':
        samples.byteswap()
    assert abs(len(samples)/rate - 3.2) < .08
    assert source.read_bytes() == original
    # After several loops and outside fades, check actual decoded signal levels.
    window = samples[int(1.2*rate):int(2.0*rate)]

    def amplitude(frequency):
        real = sum(x*math.cos(2*math.pi*frequency*i/rate) for i,x in enumerate(window))
        imag = sum(x*math.sin(2*math.pi*frequency*i/rate) for i,x in enumerate(window))
        return 2*math.hypot(real, imag)/len(window)

    assert .18 < amplitude(440) < .22
    assert .026 < amplitude(220) < .034  # .2 source amplitude × .15 music gain


def test_bundled_theme_exists():
    theme = Path(__file__).resolve().parents[1]/'music library'/music.BACKGROUND_TRACK
    assert theme.is_file() and theme.stat().st_size > 10000
