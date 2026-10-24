# Командная строка

Источник истины для доступных аргументов — `python dub.py --help` и `python dub.py <команда> --help`. Все примеры запускаются из корня репозитория в его окружении.

В чистом source ZIP сначала выполните `python tools/make_demo.py`. Готовые mock-настройки: `python dub.py generate --config examples/demo/config.json`; используйте тот же config для fit, verify, preview и package. JSON содержит имена опций с подчёркиваниями (`batch_size`, `adapter_options`); явные CLI-флаги переопределяют defaults. Пути разрешаются из рабочего каталога: запускайте из корня проекта.

`--adapter-options` принимает JSON-объект параметров конкретной модели. Удобнее хранить его в config как `"adapter_options": {}` и добавлять поддерживаемые адаптером ключи. Кавычки JSON в командной строке зависят от оболочки.

`--preset preview` принудительно задаёт batch size 1, seed 42 и max tokens 384, включая явно переданные значения этих параметров. Он не меняет timing и loudness. Для других значений используйте `--preset optimized` и нужные флаги.

| Команда | Результат |
|---|---|
| doctor | Диагностика среды и инструментов |
| plan | Проверка манифеста и выбранной очереди |
| generate | Raw синтез с метаданными и повторным использованием валидного кэша |
| fit | Обработка raw в целевой формат и длительность |
| verify | Проверка ожидаемого аудио |
| preview | Локальный просмотр/прослушивание |
| package | Переносимый архив проверенных WAV и метаданных |

Общий шаблон:

```text
python dub.py plan --manifest examples/demo/manifest.json --output work/demo --dry-run
```

Для выборки используйте `--ids`, `--scene`, `--limit`; синтаксис списка IDs уточняйте в help. Проверяйте выбранный набор командой plan перед длительным запуском. Используйте отдельный output для независимого эксперимента.

| Группа | Аргументы |
|---|---|
| Модель | `--adapter mock` или `--adapter qwen`, `--model PATH` |
| Вычисления | `--device cpu` / `cuda:0`, `--dtype float32` / `bfloat16`, `--batch-size 4` |
| Речь | `--language Russian`, `--seed 42`, `--max-new-tokens 1024` |
| Пресет | `--preset optimized` (default) / `preview` (batch 1, seed 42, max tokens 384; перекрывает эти три аргумента) |
| Тайминг | `--timing speedup` / `pad` / `none`, `--max-speedup 2` |
| Громкость | `--loudness original` / `none`, `--gain-db 0`, `--peak-db -1` |
| Инструменты | `--ffmpeg ffmpeg` |
| Сеть | Офлайн по умолчанию, `--allow-download` снимает офлайн-ограничения библиотек; каталог модели остаётся локальным |

Не каждый аргумент применим ко всем командам и адаптерам. `speedup` ускоряет длинное аудио с сохранением высоты тона и дополняет короткое тишиной. `pad` не ускоряет речь: слишком длинная запись требует решения. `none` сохраняет длительность синтеза, поэтому точная совместимость с игровым таймингом не гарантируется.

`original` ориентируется на громкость оригинала; пик может ограничить достижимое усиление. `none` отключает сопоставление громкости, но `gain-db` и ограничение пика остаются отдельными параметрами. Для оценки необработанного синтеза слушайте raw WAV.

Пример отдельной обработки без нового синтеза:

```text
python dub.py fit --manifest examples/demo/manifest.json --output work/demo --adapter mock --timing speedup --max-speedup 2 --loudness original --gain-db 0 --peak-db -1
python dub.py verify --manifest examples/demo/manifest.json --output work/demo --adapter mock
```

Архив package не является установщиком игры. Частичное покрытие указывайте явно; не смешивайте старые результаты с новым манифестом.
