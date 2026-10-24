"""Create redistributable synthetic test inputs; these are tones, not voices."""
import json
from pathlib import Path
import math
import struct
import wave


def main():
    root = Path(__file__).resolve().parents[1] / 'examples' / 'demo'
    root.mkdir(parents=True, exist_ok=True)
    with wave.open(str(root / 'reference.wav'), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(24000)
        f.writeframes(b''.join(struct.pack('<h', int(3000 * math.sin(2 * math.pi * 330 * i / 24000)))
                              for i in range(24000)))
    data = {'schema_version': 1, 'lines': [
        {'id': 'demo-001', 'speaker': 'demo', 'text': 'Это демонстрационная реплика.',
         'reference': 'reference.wav', 'original': 'reference.wav', 'scene': 'intro',
         'format': {'sample_rate': 24000, 'channels': 1, 'frames': 24000}}]}
    (root / 'manifest.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    print(root)


if __name__ == '__main__':
    main()
