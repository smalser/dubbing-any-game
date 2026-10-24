# Universal Dubbing

Локальный конвейер нейроозвучки: проверенный манифест реплик → синтез → подгонка → техническая проверка → переносимый архив WAV. Код ядра не зависит от игры и не требует конкретной ОС. Модели подключаются через адаптеры.

Это исходная переносимая версия, а не обещание автоматического перевода любой игры. Извлечение, связь текста с голосами, игровые форматы, упаковка мода и проверка в игре зависят от движка и конкретного проекта. Для этих этапов используйте [Universal Modder](https://github.com/rehan-remade/universal-modder) и отдельную интеграцию. Наличие Python API у модели также не означает поддержку всех устройств и ОС.

## Быстрый старт

Нужен Python 3.10+; для обработки аудио — FFmpeg в PATH или явный `--ffmpeg`. Выполните команды из корня этого репозитория:

```text
python -m venv .venv
```

Активируйте окружение: Windows PowerShell — `.venv/Scripts/Activate.ps1`, Linux/macOS — `source .venv/bin/activate`. Если активация ограничена политикой оболочки, вызывайте Python окружения напрямую.

```text
python -m pip install --upgrade pip
python -m pip install -e .
python dub.py --help
python dub.py doctor
python tools/make_demo.py
python dub.py plan --config examples/demo/config.json
python dub.py generate --config examples/demo/config.json
python dub.py fit --config examples/demo/config.json
python dub.py verify --config examples/demo/config.json
python dub.py preview --config examples/demo/config.json
python dub.py package --config examples/demo/config.json
```

`tools/make_demo.py` создаёт синтетические исходники и обязателен перед demo в чистом source ZIP. `--config` читает JSON defaults; явные CLI-флаги их переопределяют. Один config используйте на всех этапах.

`mock` создаёт технический сигнал и проверяет конвейер; он не произносит текст и не проверяет качество нейроозвучки. Демонстрационный набор должен содержать только синтетические или разрешённые материалы.

Для Qwen установите дополнительные зависимости. Для настоящего клонирования замените тестовый тон в манифесте чистой разрешённой записью говорящего:

```text
python -m pip install -e ".[qwen]"
python dub.py generate --manifest examples/demo/manifest.json --output work/qwen-demo --adapter qwen --model /path/to/local/model --device cuda:0 --dtype bfloat16 --language Russian --batch-size 4 --seed 42 --max-new-tokens 1024
```

Выбирайте `--device` и `--dtype` под свою модель и оборудование. На CPU начните с `--device cpu --dtype float32`; поддержка и скорость зависят от адаптера. По умолчанию модель используется офлайн: веса должны быть уже доступны локально. `--allow-download` снимает офлайн-ограничения библиотек, но текущий Qwen-адаптер по-прежнему требует локальный каталог модели и не скачивает его автоматически. Не выбирайте это разрешение без необходимости.

Помощник установки умеет показать план: `python tools/bootstrap.py --extra qwen --dry-run`. Подробнее — [установка](docs/SETUP.md), [плейбук для агента](docs/PLAYBOOK.md), [CLI](docs/CLI.md), [архитектура](docs/ARCHITECTURE.md).

## Примеры до и после

Локальная страница [examples/comparison/index.html](examples/comparison/index.html) показывает реальные пары оригинала и синтеза, подготовленные из экспериментов исходного проекта. Аудио может поставляться отдельно и не входит автоматически в публичный Git. До публикации проверьте право распространять каждую запись и её производную. Независимость ядра от игры не снимает ограничений на исходные материалы.

## Границы проверки

На Windows прошли 13 автоматических CPU-тестов, установка в новое окружение и маршрут mock/FFmpeg. Реальный Qwen проверен на одной реплике. [Шаблон CI для Windows/Linux/macOS](docs/CI_SETUP.md) подготовлен, но не активирован и не выполнен. Подробности и ограничения — в [VALIDATION.md](docs/VALIDATION.md).

`package` создаёт проверенный ZIP с WAV и метаданными. Он не собирает игровой PAK/BNK/WEM и не устанавливает мод. Прослушивание, проверка текста, голоса и прохождение сцены выполняются отдельно. ASR и совпадение длительностей не подтверждают актёрскую подачу.

Публичный репозиторий должен содержать код, документацию и разрешённые примеры. Модели, игровые архивы, извлечённые оригиналы, референсы чужих голосов, окружения и рабочие результаты храните локально. См. [подготовку к распространению](docs/RELEASING.md).
