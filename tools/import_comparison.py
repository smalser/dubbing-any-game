"""Import a local historical comparison. Media stays excluded from source releases."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import shutil


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source', type=Path, required=True, help='Comparison folder with test-manifest.json')
    p.add_argument('--assets-root', type=Path, required=True, help='Root for relative original reference paths')
    p.add_argument('--output', type=Path, default=Path(__file__).resolve().parents[1] / 'examples' / 'comparison')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    rows = json.loads((a.source / 'test-manifest.json').read_text(encoding='utf-8'))
    plan = []
    for r in rows:
        name = r['speaker'].lower()
        if not name.isascii() or not name.isalpha():
            p.error('Expected safe alphabetic speaker filename')
        before = (a.assets_root / r['reference_original'].replace('\\', '/')).resolve()
        after = (a.source / (name + '-qwen.wav')).resolve()
        if not before.is_file() or not after.is_file():
            p.error('Missing original/generated recording')
        plan.append((r, name, before, after))
    print(json.dumps({'examples': len(plan), 'output': str(a.output), 'includes_originals': True}))
    if a.dry_run:
        return
    (a.output / 'audio').mkdir(parents=True, exist_ok=True)
    provenance = []
    body = ['<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width">',
            '<title>Нейроозвучка — до и после</title><style>body{font:18px system-ui;background:#10151e;color:#edf1f7;max-width:960px;margin:50px auto;padding:20px}section{background:#1b2533;padding:24px;margin:20px 0;border-radius:16px}.pair{display:flex;gap:24px;flex-wrap:wrap}audio{max-width:100%}small{color:#b2bed0}</style>',
            '<h1>Нейроозвучка: до и после</h1><p>Реальные ранние примеры Nobody Wants to Die. Слева оригинальный английский голос, справа русский Qwen raw. Без подгонки длительности и выравнивания громкости: разница уровня слышна.</p>',
            '<small>Локальная галерея. Права на оригинальные игровые записи не передаются с исходным кодом. Аудио исключено из публичного пакета проекта.</small>']
    for r, name, before, after in plan:
        entry = {'speaker': r['speaker'], 'id': r['id'], 'text': r['text'], 'seed': r['seed'], 'files': {}}
        for label, source in [('before', before), ('after', after)]:
            dest = a.output / 'audio' / (name + '-' + label + '.wav')
            shutil.copyfile(source, dest)
            entry['files'][label] = {'path': 'audio/' + dest.name,
                                     'sha256': hashlib.sha256(dest.read_bytes()).hexdigest()}
        provenance.append(entry)
        body += [f'<section><h2>{html.escape(r["speaker"])}</h2><p>{html.escape(r["text"])}</p><div class="pair">',
                 f'<div><p>До · EN</p><audio controls preload="none" src="audio/{name}-before.wav"></audio></div>',
                 f'<div><p>После · RU</p><audio controls preload="none" src="audio/{name}-after.wav"></audio></div></div></section>']
    body.append('</html>')
    (a.output / 'index.html').write_text('\n'.join(body), encoding='utf-8')
    (a.output / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
