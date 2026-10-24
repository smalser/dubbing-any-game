"""Adapter contract: load(config), synthesize(rows, config) -> [(samples, rate)].

Custom adapters are trusted Python classes selected with module:Class.
They receive resolved reference paths; they must return one finite waveform per row.
"""
import importlib
from pathlib import Path


class Mock:
    """Deterministic test tone, NOT speech. Never used as a fallback."""
    def load(self, config):
        pass

    def synthesize(self, rows, config):
        import numpy as np
        return [(0.1 * np.sin(2 * np.pi * 220 * np.arange(12000) / 24000), 24000)
                for _ in rows]


class Qwen:
    def load(self, config):
        forbidden = {'text', 'language', 'voice_clone_prompt', 'non_streaming_mode', 'max_new_tokens', 'ref_audio', 'ref_text', 'x_vector_only_mode'}
        if set(config['adapter_options']) & forbidden:
            raise ValueError('Adapter options cannot override pipeline text, references or token limit')
        import torch
        from qwen_tts import Qwen3TTSModel
        self.torch = torch
        self.model = Qwen3TTSModel.from_pretrained(
            config['model'], device_map=config['device'],
            dtype=getattr(torch, config['dtype']), attn_implementation=config['attention'])
        self.prompts = {}

    def synthesize(self, rows, config):
        import numpy as np
        import soundfile as sf
        self.torch.manual_seed(config['seed'])
        np.random.seed(config['seed'])
        for row in rows:
            ref = row['reference']
            if ref not in self.prompts:
                audio, rate = sf.read(ref, always_2d=True, dtype='float32')
                self.prompts[ref] = self.model.create_voice_clone_prompt(
                    ref_audio=(audio.mean(axis=1), rate), x_vector_only_mode=True)[0]
        waves, rate = self.model.generate_voice_clone(
            text=[r['text'] for r in rows], language=[config['language']] * len(rows),
            voice_clone_prompt=[self.prompts[r['reference']] for r in rows],
            non_streaming_mode=True, max_new_tokens=config['max_new_tokens'], **config['adapter_options'])
        return [(np.asarray(w).reshape(-1), rate) for w in waves]


def create(name):
    if name == 'mock':
        return Mock()
    if name == 'qwen':
        return Qwen()
    module, sep, cls = name.partition(':')
    if not sep:
        raise ValueError('Adapter must be mock, qwen or module:Class')
    return getattr(importlib.import_module(module), cls)()
