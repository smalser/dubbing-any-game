# CLI: локальные задания

CPU-пример не требует окружения Qwen: `python examples/demo.py`. Ниже reference adapter **Windows + Nobody Wants to Die**, а не универсальный установщик любой игры.

## Локальные зависимости

Подготовить собственные `data/story-manifest.json` и `data/voices.json` по схеме из examples. Реальные audio/text/assets хранить локально в gitignored `work/` и `data/`.

```text
work/
  models/Qwen3-TTS-1.7B-Base/  # модель и speech tokenizer, скачаны отдельно
  tools/
    repak/repak.exe
    vgmstream/vgmstream-cli.exe
    wwiser.pyz
    wwav.py
  extracted/                 # собственные локально извлечённые banks/media
  story-originals/           # decoded originals и wwiser XML
data/
  story-manifest.json
  voices.json
```

Tools не скачиваются автоматически. Источники — [кейс](NWTD_CASE_STUDY.md). Перед использованием проверить происхождение и лицензии. `prepare` извлекает **указанные в собственном manifest** banks из `detnoir/Content/Paks/pakchunk0-Windows.pak`, получает source ID через wwiser, извлекает media и декодирует через vgmstream. Извлечение Articy и построение verified text/speaker map — отдельный исследовательский этап, не скрытая функция `prepare`.

FFmpeg должен поддерживать `rubberband` и `loudnorm`. GPU-stage требует локального Qwen/PyTorch/CUDA в том Python, которым запускается `dub.py`. PowerShell-обёртка `Run-Dubbing.ps1` ожидает `work/qwen-env/Scripts/python.exe`; при другом расположении используйте Python напрямую.

## План, запуск и прогресс

```powershell
python scripts/dub.py plan --manifest examples/manifest.json --output outputs/plan
python scripts/dub.py plan --manifest data/story-manifest.json --scene 01_00_00_Cinema

# Реальное задание, игра должна быть закрыта:
python scripts/dub.py run --game "X:\Games\Nobody Wants to Die" --manifest data/story-manifest.json --voices data/voices.json --output outputs/story --preset optimized
python scripts/dub.py status --output outputs/story
```

`run` выполняет prepare→generate→fit→build. **Не устанавливает** пакет в игру. Для одной сцены добавить `--scene <substring>`, для первых N ready записей — `--limit N`. Manifest order не пересортировывается по длине текста.

В output сохраняются `events.jsonl`, `status.json`, `prepared-manifest.json`, raw WAV/JSON, fit/build manifests. Console печатает этап/готово/ETA. Оценка по batch_done приблизительная: разные тексты, холодная загрузка и CPU-этапы меняют реальное время до результата.

```powershell
python scripts/dub.py stop --output outputs/story
python scripts/dub.py resume --game "X:\Games\Nobody Wants to Die" --output outputs/story
```

`stop` создаёт STOP, worker остановится **после текущего batch**. `resume` убирает STOP и запускает тот же flow; передавайте те же manifest/voices/preset и selection, что при исходном запуске. Валидные raw пропускаются по fingerprint/hash. Locks: `<output>/RUNNING.lock` и `work/GPU-GENERATION.lock`; после аварии удалять только убедившись, что PID уже не работает.

`run --no-fit --no-build` выполняет prepare+generation. Ступени `prepare`, `generate`, `fit`, `build`, `preview`, `install` можно вызывать отдельно. `generate` требует готовые voice references; оригинальные XML/WAV нужны последующим fit/build. `run` по умолчанию перекрывает CPU-подготовку (`--prepare-workers 4`) с одним GPU worker. `--sequential-prepare` возвращает последовательный режим. Статусы CPU и TTS независимы: `preparation-status.json` и `status.json`. ETA синтеза считать по свежим `batch_done` текущего запуска, cached показывать отдельно; не смешивать старые события с текущей скоростью. Никакой параллельной GPU-генерации вместе с игрой.

## Presets и длительность

`optimized`: batch4, seed от ID группы, max1024. `preview`: batch1, fixed seed42, max384; preset переопределяет переданные batch/seed/token flags. Он возвращает настройки раннего одиночного теста, а не отменяет обработку.

`--batch-size`, `--seed`, `--seed-mode fixed|batch`, `--max-new-tokens`, `--threads`, `--model`, `--voices` задают синтез. Изменение параметров меняет fingerprint, поэтому для A/B лучше отдельный output.

| `--timing` | Поведение |
|---|---|
| `speedup` | Default: ускорить длинное, короткое дополнить тишиной |
| `both` | Ускорять/замедлять: отдельный экспериментальный режим |
| `pad` | Естественный темп, длинное отвергнуть без обрезания речи |
| `none` | Переменная длительность без tempo/padding; возможен рассинхрон |

`--no-trim` сохраняет внешнюю тишину raw. Обработка использует исходные rate/channels; в speedup/both/pad сохраняется точное исходное число кадров.

## Громкость без повторной генерации

```powershell
python scripts/dub.py fit --output outputs/story --timing speedup --loudness lufs --target-lufs -20 --gain-db 1 --peak-db -1
python scripts/dub.py build --output outputs/story
python scripts/dub.py preview --output outputs/story
```

- `--loudness original` (default): сопоставить full-file RMS с оригиналом; тишина влияет на результат.
- `--loudness lufs`: двухпроходный FFmpeg loudnorm; короткие/неизмеримые clips переходят на original RMS с явным warning в отчёте.
- `--loudness reference`: экспериментальная привязка LUFS к каждому оригиналу постоянным gain; короткие неизмеримые слова — active RMS. `--target-lufs` здесь не задаёт общую цель. Записываются измерения/fallback/остаточная ошибка; улучшение на слух не подтверждено, default не менялся.
- `--loudness none`: без нормализации; gain и peak safety продолжают действовать.
- `--target-lufs -20`, `--gain-db 0`, `--peak-db -1`: defaults. После peak clamp/дополнительного gain фактическая loudness может отличаться от цели.

`fit` всегда берёт raw, а не предыдущий fitted. `build` проверяет hashes raw/fitted/original; после изменения параметров нужен новый fit. Само изменение аргумента не обновляет PAK.

## Частичная сборка и установка

```powershell
python scripts/dub.py fit --output outputs/story --available-only
python scripts/dub.py build --output outputs/story --available-only
python scripts/dub.py install --game "X:\Games\Nobody Wants to Die" --output outputs/story
```

`--available-only` для fit/build/preview выбирает completed raw с совпадающим текстом/speaker/hash, исключая token-limit flagged clips. Это техническая готовность, не принятие качества на слух. Coverage частичного PAK сохраняется.

Install отдельной командой проверяет закрытую игру, PAK/hash, делает backup, отвергает неизвестные/частичные пересечения. Известные собственные opening PAK отключаются только при полном покрытии их entries. В `install-manifest.json` точный путь backup/rollback. Игровые archives и saves не изменяются.

## Проверки

```powershell
python -m unittest discover -s tests -v
python examples/demo.py
```

Тест resume использует подставной синтезатор и проверяет skip/invalidation/STOP. CPU tests проверяют natural tempo короткого файла, точные кадры, ускорение длинного и отказ `pad` при длинной записи. Они не используют GPU/игру/сеть и не подтверждают качество голосов. Добавлены синтетические проверки reference LUFS/коротких слов и bank aliases/исходного PCM. В тесте упаковки внешние игровые инструменты подставные: он проверяет guards и набор entries, а не настоящий Wwise/Unreal runtime. Полный ASR новой очереди и runtime playthrough — отдельные этапы.
