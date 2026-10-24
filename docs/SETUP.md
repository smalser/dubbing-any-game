# Установка

Для основного пути Qwen начните с [полного гайда установки модели](QWEN.md). Здесь — общие зависимости и техническая диагностика. Навык агента устанавливается [отдельно](SKILL.md).

Python должен быть доступен командой `python` (на части систем — `python3`). Используйте Python 3.10+ и отдельное `.venv`. Уточняйте совместимые версии в pyproject.toml и требованиях выбранной TTS-модели.

```text
python -m venv .venv
```

| Среда | Активация | Python без активации |
|---|---|---|
| Windows PowerShell | `.venv/Scripts/Activate.ps1` | `.venv/Scripts/python.exe` |
| Linux/macOS shell | `source .venv/bin/activate` | `.venv/bin/python` |

```text
python -m pip install --upgrade pip
python -m pip install -e .
python tools/make_demo.py
python dub.py doctor --config examples/demo/config.json
```

Установите FFmpeg средствами вашей ОС и убедитесь, что исполняемый файл доступен. Можно передать `--ffmpeg /path/to/ffmpeg`. Поддержка нужных фильтров зависит от сборки FFmpeg.

Для Qwen:

```text
python -m pip install -e ".[qwen]"
```

Для игрового плейбука установите обязательный Universal Modder (нужен Git):

```text
python -m pip install -e ".[game]"
python dub.py doctor --config examples/demo/config.json --game-tools
python -m um --version
```

Для общего окружения используйте `python -m pip install -e ".[qwen,game]"`. Помощник установки: `python tools/bootstrap.py --extra qwen --game-tools --dry-run`. Точный revision Universal Modder закреплён в pyproject.toml и проверяется doctor. Профиль не вызывает сервисы генерации: оплачиваемые инструменты Universal Modder не запускаются автоматически.

Выбор PyTorch/CUDA зависит от оборудования и драйвера; дополнительные зависимости проекта не гарантируют правильную GPU-сборку для любой машины. Установите подходящую версию по официальной инструкции PyTorch. Веса модели приобретайте/загружайте по её собственным условиям, сохраняйте локально и передавайте через `--model`.

Doctor с конфигурацией Qwen проверяет наличие Python-пакетов, config.json/весов, доступность устройства и reference WAV. Он не загружает модель: совместимость ревизии, dtype и устройства подтверждается только отдельным коротким синтезом и прослушиванием. Для внешнего адаптера doctor честно сообщает отсутствие его собственного preflight. `plan` и dry-run проверяют выборку и пути, но не заменяют doctor.

Подтверждённой общей матрицы Python/PyTorch/CUDA/Qwen у проекта пока нет. Версия `qwen-tts` закреплена; её транзитивные зависимости — нет. После успешной установки сохраните `python -m pip freeze` и `python -m pip check`, модельный revision и `ffmpeg -version` в приватной рабочей области. Не выдавайте диапазон Python >=3.10 за тест всех сочетаний.

Помощник подготовки:

```text
python tools/bootstrap.py --extra qwen --dry-run
```

Сначала изучите план и `--help`. По умолчанию синтез не должен скачивать веса. Флаг `--allow-download` снимает офлайн-ограничения библиотек. Текущий Qwen-адаптер требует локальный каталог даже с этим флагом: веса загружаются отдельно. Для воспроизводимости фиксируйте версию модели.

Базовый CPU smoke-тест с mock не требует весов. Проверка Qwen на конкретной ОС и GPU — отдельный этап. MPS и другие ускорители нельзя считать поддержанными без проверки адаптера и зависимостей.

В чистом source ZIP перед demo выполните `python tools/make_demo.py`. Он создаёт синтетические исходники без игровых материалов.

Для отдельной явной загрузки модели:

```text
python tools/download_model.py --repo ORGANIZATION/MODEL --revision PINNED_COMMIT --output models/tts --dry-run
```

Замените placeholders выбранным репозиторием и закреплённым commit. Dry-run только показывает план. Уберите флаг после проверки лицензии, размера и разрешения на загрузку. Синтез не вызывает этот помощник автоматически.

## Проверка установки с mock

`mock` создаёт тестовый звуковой сигнал, а не речь. Этот раздел нужен для диагностики обработки WAV; для озвучки используйте Qwen или другой TTS-адаптер.

Нужны **Python 3.10+** и **FFmpeg** в PATH; для ускорения аудио нужен фильтр Rubber Band. GPU, веса модели и Universal Modder для этого примера не требуются. Совместимость зависимостей и способы установки описаны в [инструкции выше](#установка).

Все команды выполняйте из корня репозитория. Создайте окружение:

```text
python -m venv .venv
```

| Оболочка | Активация |
|---|---|
| Windows PowerShell | `.venv/Scripts/Activate.ps1` |
| Linux/macOS | `source .venv/bin/activate` |

Если активация недоступна, вместо `python` вызывайте `.venv/Scripts/python.exe` на Windows или `.venv/bin/python` на Linux/macOS.

Установите зависимости и подготовьте синтетический пример:

```text
python -m pip install -e .
python dub.py --help
python tools/make_demo.py
python dub.py doctor --config examples/demo/config.json
python dub.py plan --config examples/demo/config.json
python dub.py generate --config examples/demo/config.json --dry-run
```

Продолжайте после успешного `doctor` и проверки списка IDs в `plan`. `make_demo.py` создаёт тестовый тон и перезаписывает демонстрационный манифест; собственные данные храните отдельно.

```text
python dub.py generate --config examples/demo/config.json
python dub.py fit --config examples/demo/config.json
python dub.py verify --config examples/demo/config.json
python dub.py preview --config examples/demo/config.json
python dub.py package --config examples/demo/config.json
```

**Ожидаемый результат:** одна обработанная реплика `demo-001` в `work/demo/`. Mock генерирует тон, поэтому в этом примере вы услышите сигнал, а не произнесённый текст.

| Путь внутри `work/demo/` | Что в нём |
|---|---|
| `raw/` | Синтез до подгонки, с метаданными |
| `fitted/` | WAV после обработки |
| `verification.json` | Результат технической проверки |
| `listen.html` | Страница прослушивания; откройте её в браузере |
| `audio-export.zip` | Проверенные WAV и манифест экспорта |
| `package.json` | Размер и SHA256 архива |
| `status.json`, `events.jsonl` | Состояние и журнал этапов |
