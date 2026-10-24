"""Shared waveform validation; intermediate float audio may exceed PCM range."""
def audio(path, *, pcm_range=True):
    import numpy as np
    import soundfile as sf
    a, sr = sf.read(path, dtype='float32', always_2d=True)
    if not len(a) or not np.isfinite(a).all() or a.shape[1] not in range(1, 9):
        raise ValueError(f'Empty/nonfinite/unsupported audio: {path}')
    peak = float(np.max(np.abs(a)))
    if peak <= 1e-7 or (pcm_range and peak >= 1):
        raise ValueError(f'Silent or clipped audio: {path}')
    return a, sr
