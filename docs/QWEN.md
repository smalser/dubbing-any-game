# Установка Qwen и первая произнесённая реплика

Эта инструкция проверяет **речь**, независимо от игры. Понадобятся рабочая копия Universal Dubbing, Python, FFmpeg, локальная модель и ваша разрешённая запись голоса. Результат — WAV и страница прослушивания. После этого переходите к игровому пилоту через [Skill](SKILL.md).

## 1. Подготовьте окружение

Откройте терминал в папке репозитория, где лежит `dub.py`. Используйте отдельное окружение по [SETUP.md](SETUP.md). Для повторения локально проверенной конфигурации проекта используйте Python 3.11; общая матрица совместимости не заявляется. Авторы Qwen также описывают отдельное окружение Python 3.12 в [официальной инструкции](https://github.com/QwenLM/Qwen3-TTS#quickstart).

```text
python --version
python -m venv .venv
```

Если Python не установлен, возьмите установщик с [python.org](https://www.python.org/downloads/). Если `python --version` показывает другую версию, выберите нужный интерпретатор до создания окружения: например, `py -3.11 -m venv .venv` на Windows при установленном Python 3.11 или `python3.11 -m venv .venv` на Linux/macOS. Не считайте, что команда `python` автоматически выбирает 3.11.

Если `.venv` уже подготовлено, повторно создавать его не нужно. Активируйте:

| Оболочка | Команда |
|---|---|
| Windows PowerShell | `.venv/Scripts/Activate.ps1` |
| Linux/macOS | `source .venv/bin/activate` |

При запрете активации заменяйте `python` во всех командах на `.venv/Scripts/python.exe` (Windows) или `.venv/bin/python` (Linux/macOS). Проверьте `python -c "import sys; print(sys.executable)"`: путь должен вести в выбранное окружение.

Установите FFmpeg по [ссылкам для вашей ОС](https://ffmpeg.org/download.html), добавьте его каталог в PATH и откройте новый терминал с активированным окружением. Проверьте `ffmpeg -version`. Для подгонки игровых реплик с ускорением нужен фильтр Rubber Band; `doctor` проверит его. Первый речевой тест ниже не ускоряет звук.

## 2. Установите PyTorch и Qwen

Откройте [официальный установщик PyTorch](https://pytorch.org/get-started/locally/), выберите свою ОС, Pip, Python и вычислительную платформу. Для NVIDIA выбирайте совместимую с драйвером CUDA-сборку, для процессора — CPU. Выполните предложенную команду **в этом окружении**, используя `python -m pip` вместо `pip`/`pip3`. Не выбирайте CUDA на компьютере без поддерживаемой NVIDIA GPU.

Затем установите адаптер проекта:

```text
python -m pip install -e ".[qwen]"
python -m pip check
python -c "import torch, qwen_tts; print('torch:', torch.__version__); print('CUDA:', torch.cuda.is_available()); print('bfloat16:', torch.cuda.is_bf16_supported() if torch.cuda.is_available() else False)"
```

Проект закрепляет `qwen-tts==0.1.1`. Пакет и веса модели устанавливаются отдельно. Для игрового исследования позже добавьте `python -m pip install -e ".[game]"` ([сначала установите и проверьте Git](SETUP.md)); для этого речевого теста Universal Modder не нужен.

Встроенный конфиг теста использует CPU / float32, чтобы не предполагать наличие конкретной видеокарты. Это может быть медленно и требовать значительной RAM; CPU-синтез не является проверенной здесь конфигурацией. Проверенный ранее маршрут проекта — NVIDIA CUDA / bfloat16 / SDPA. Если проверка CUDA и bfloat16 выше дала `True`, измените `device` на `cuda:0`, `dtype` на `bfloat16` в `examples/qwen/config.json` **до запуска**. SDPA уже задан; FlashAttention для этого рецепта не требуется. Другие устройства и dtype требуют отдельной проверки.

## 3. Скачайте полную модель

Используйте именно [Qwen/Qwen3-TTS-12Hz-1.7B-Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base). Встроенный адаптер вызывает клонирование голоса Base; варианты CustomVoice и VoiceDesign не являются взаимозаменяемыми. Согласно карточке, лицензия весов — Apache-2.0; отдельно проверьте право использования референса.

Зафиксированный для этой инструкции revision: `fd4b254389122332181a7c3db7f27e918eec64e3`. По [метаданным официального репозитория](https://huggingface.co/api/models/Qwen/Qwen3-TTS-12Hz-1.7B-Base?blobs=true), проверенным 24 октября 2026, полный снимок занимает около **4,54 GB**. Дополнительно нужны место под Python/PyTorch, временную загрузку и результаты. Размер файлов не равен требуемой VRAM; универсальный минимум памяти проектом не измерен. Этот revision проверен по метаданным, а не новым синтезом.

Сначала посмотрите локальный план (он ничего не скачивает и не проверяет доступность сервера):

```text
python tools/download_model.py --repo Qwen/Qwen3-TTS-12Hz-1.7B-Base --revision fd4b254389122332181a7c3db7f27e918eec64e3 --output models/Qwen3-TTS-12Hz-1.7B-Base --dry-run
```

Следующая команда **скачивает веса**. Выполняйте её после проверки размера и условий; агент должен иметь разрешение пользователя на загрузку:

```text
python tools/download_model.py --repo Qwen/Qwen3-TTS-12Hz-1.7B-Base --revision fd4b254389122332181a7c3db7f27e918eec64e3 --output models/Qwen3-TTS-12Hz-1.7B-Base
```

Скачивается весь снимок, включая `speech_tokenizer/`, текстовый tokenizer и конфигурации. Одного `model.safetensors` недостаточно. Если веса уже есть, укажите их каталог в поле `model` конфига и не загружайте повторно. Не смешивайте разные revisions в одном каталоге. При прерывании повторите ту же команду, затем дождитесь успешного завершения.

После загрузки должны существовать как минимум:

```text
models/Qwen3-TTS-12Hz-1.7B-Base/
  config.json
  model.safetensors
  tokenizer_config.json
  vocab.json
  merges.txt
  speech_tokenizer/
    config.json
    model.safetensors
```

Это ориентир, не полный список для ручного скачивания. Синтез использует локальный каталог и работает офлайн; `--allow-download` для него не нужен и не заменяет загрузку модели.

## 4. Добавьте образец голоса

Создайте папку `work/qwen-voice-check/input/`. Поместите в неё файл `reference.wav`: чистую короткую запись одного человека без музыки, наложения голосов и клиппинга, на использование которой у вас есть разрешение. Для первой проверки можно записать собственный голос, например несколько секунд обычной речи. Тестовый тон из demo для этого не подходит.

Если исходник в другом формате, сконвертируйте его, заменив `path/to/my-recording` на свой путь:

```text
ffmpeg -i "path/to/my-recording" -ac 1 -ar 24000 -c:a pcm_s16le work/qwen-voice-check/input/reference.wav
```

Не перезаписывайте нужную запись: при наличии файла выберите новое имя и обновите `reference` в манифесте. Текущий адаптер использует голосовой вектор (`x_vector_only_mode=True`), поэтому отдельная расшифровка референса не требуется.

Готовые настройки лежат в [examples/qwen/config.json](../examples/qwen/config.json), текст — в [manifest.json](../examples/qwen/manifest.json). В манифесте одна фраза: «Привет! Это проверка локальной озвучки». `timing: none` сохраняет длительность синтеза, `loudness: none` не требует оригинала. Поле `frames` здесь заполняет схему и не задаёт игровой тайминг. Для игры нужен отдельный манифест с измеренными кадрами и соответствующей подгонкой.

## 5. Проверьте готовность и синтезируйте

Все команды запускайте из корня проекта, с тем же Python и одним config:

```text
python dub.py doctor --config examples/qwen/config.json
python dub.py plan --config examples/qwen/config.json
python dub.py generate --config examples/qwen/config.json --dry-run
```

Doctor должен вернуть `ready_for_requested_checks: true`, plan — один ID `voice-check-001`. При ошибке исправьте указанный пункт до запуска. Doctor не загружает модель и не гарантирует совместимость всех зависимостей; следующая команда — реальная проверка синтеза.

Закройте игру и убедитесь, что другое задание не использует выбранную GPU. Затем:

```text
python dub.py generate --config examples/qwen/config.json
python dub.py fit --config examples/qwen/config.json
python dub.py verify --config examples/qwen/config.json
python dub.py preview --config examples/qwen/config.json
```

Откройте `work/qwen-voice-check/output/listen.html` в браузере. Вы должны услышать произнесённую фразу. Raw лежит в `output/raw/`, обработанный WAV — в `output/fitted/`. Проверьте текст, окончание фразы и сходство голоса; технический `verify` не оценивает произношение.

Для передачи проверенного аудио можно выполнить `python dub.py package --config examples/qwen/config.json`. Это WAV ZIP, не мод игры. Дальше запустите [игровой пилот со Skill](SKILL.md#как-запустить).

## Если не получилось

| Симптом | Что проверить |
|---|---|
| `python` или `ffmpeg` не найден | Установку, PATH и новый терминал; Python должен быть из выбранного окружения |
| Не импортируется `torch`/`qwen_tts` | `sys.executable`, установку `.[qwen]`, `python -m pip check` |
| Doctor сообщает отсутствие `rubberband` | Используйте [сборку FFmpeg с нужным фильтром](SETUP.md#если-ffmpeg-не-содержит-rubber-band) для игрового ускорения |
| CUDA недоступна | GPU, драйвер и сборку PyTorch; установка пакета Qwen сама по себе не включает CUDA |
| Ошибка BF16 | Поддержку bfloat16 устройством; выберите совместимый dtype и отдельно проверьте синтез |
| `model:local_files` не прошёл | Путь `model` относительно корня проекта и завершённую загрузку |
| Ошибка загрузки tokenizer офлайн | Полный снимок, включая `speech_tokenizer/`; не отключайте офлайн-режим для маскировки неполной загрузки |
| `manifest:references` не прошёл | Точный путь `work/qwen-voice-check/input/reference.wav`, читаемый ненулевой WAV |
| Не хватает памяти | Один worker, отсутствие игры/другого синтеза; preview уже использует batch 1. Другая модель/устройство — отдельный эксперимент |
| Речь оборвана | Прослушать raw; preview ограничивает генерацию 384 токенами. Для других значений используйте optimized и явные параметры по CLI |
| Хочется изменить громкость | Меняйте настройки обработки и повторяйте `fit`, затем `verify`; raw сохраняется |

Сохраните версии через `python -m pip freeze`, `ffmpeg -version`, выбранный revision и конфиг в приватном каталоге задания. Реально проверенные платформы и ограничения — в [VALIDATION.md](VALIDATION.md).
