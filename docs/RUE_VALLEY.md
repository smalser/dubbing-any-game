# Rue Valley: воспроизводимый пилот Unity Mono / FMOD

Маршрут ниже проверен на Windows x64, Rue Valley build 1.1.1v1, Unity Mono 2022.3.62f2 и FMOD 2.02.04. Это **пилот четырёх реплик доктора Финка**. Финальная сборка managed-service runtime прошла естественный игровой путь для всех четырёх: UI fragment → Articy sound object/GUID → replacement start → end/stop. Две полные реплики подтверждены записью игрового звука с корреляцией 0,99644 и 0,99799 к подготовленным WAV; третья пропущена интервалом между записями, четвёртая записана частично. Качество актёрской подачи и полная слуховая проверка остаются `pending`; первая короткая реплика ускорена примерно вдвое. Оригинальные банки, игровые DLL и пользовательские сохранения сохраняются.

Команды выполняются из корня репозитория в PowerShell. Все пути ниже задаёт пользователь; локальные игровые материалы, модель, references и результаты остаются в `work/` и не входят в публичный репозиторий.

## Зависимости и исследование

Нужны Python3.10+, FFmpeg, Git, локальная Qwen3-TTS-12Hz-1.7B-Base, совместимые PyTorch/CUDA для выбранного устройства, .NET **SDK**, официальный BepInEx5 Windows x64 и собственная установка игры. Наличие .NET runtime не заменяет SDK. Модель/оригинальные голоса наружу не отправляются.

```powershell
python -m venv .venv
$python = '.venv/Scripts/python.exe'
& $python -m pip install -e ".[game,unity,qwen]"
& $python -m um --version
& $python tools/make_demo.py
& $python dub.py doctor --config examples/demo/config.json --game-tools
```

`game` extra закрепляет [Universal Modder](https://github.com/rehan-remade/universal-modder) на commit `c1dff21663665dd17af289744a301b66e369605e`; исполняемые этапы интеграции проверяют provenance установленного toolkit и его CLI. Копия исходников без установленного pinned extra эту проверку не заменяет. `unity` закрепляет UnityPy1.25.4/TypeTreeGeneratorAPI0.0.10. Установка Qwen extra сама по себе не скачивает и не настраивает локальные веса/PyTorch/CUDA; см. [SETUP.md](SETUP.md).

```powershell
$game = Read-Host 'Каталог собственной Rue Valley'
$model = Read-Host 'Каталог локальной Qwen3-TTS-12Hz-1.7B-Base'
$run = 'work/rue-valley-pilot-new'
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
& $python -m um scan $game --json
& $python -m um kb search 'Rue Valley'
```

Сначала сверить движок/build и [INTEGRATION_GATE.md](INTEGRATION_GATE.md). Другая версия игры требует повторной проверки типов, локализации, GUID и FMOD ABI. Не запускать GPU-генерацию параллельно с игрой.

## Extract → exact mapping → выбор четырёх строк

```powershell
& $python -m dubbing.integrations.rue_valley.extract --game $game --output "$run/extracted" --dry-run
& $python -m dubbing.integrations.rue_valley.extract --game $game --output "$run/extracted"
& $python -m dubbing.integrations.rue_valley.mapping --objects "$run/extracted/objects.jsonl" --output "$run/mapping" --dry-run
& $python -m dubbing.integrations.rue_valley.mapping --objects "$run/extracted/objects.jsonl" --output "$run/mapping"
```

Extractor восстанавливает serialized typetree из Managed assemblies игры и читает `resources.assets`. Mapping связывает localization key→RU/EN→speaker ID→SoundEffect ID→FmodId через точные сериализованные ссылки. Он сохраняет `mapping.json`, `coverage.csv/json`, `unresolved.json`; fuzzy matching не используется. В исследованном build получено 3424 exact joins из 61583 фрагментов; 58159 остаются в unresolved, в основном как неозвученные фрагменты. Это не счётчик всех звуковых assets или готовых записей.

Четыре выбранных ID ниже относятся к NPC `Dr. Finck`, speaker `72057658462437409`, ветке `PROLOGUE / The End of First Session / Still With Me Mr. Harrow`. Список задаёт порядок пилота; ветвящийся сюжет не становится единственной линейной последовательностью. Для естественного прохождения второй строки `DFr_7A9A0B74` нужна черта «Бессердечие» и ответ «Мы закончили?»: далее идут `DFr_4FB0B8E0` → `DFr_F5DD0277` → `DFr_7A9A0B74`. Обычный ответ «Просто кивнуть» ведёт к другой реплике.

```powershell
@'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1])
ids = ['72057632692673839', '72057598332921193',
       '72057598332921229', '72057598332921362']
rows = json.loads((root/'mapping/mapping.json').read_text(encoding='utf-8'))['entries']
by_id = {row['id']: row for row in rows}
selected = [by_id[ident] for ident in ids]
assert all(row['speaker_id'] == '72057658462437409' for row in selected)
assert len({row['event_guid'] for row in selected}) == 4
with (root/'selection.json').open('x', encoding='utf-8') as stream:
    json.dump({'selection': 'four exact Dr. Finck pilot fragments; branch order not asserted',
               'entries': selected}, stream, ensure_ascii=False, indent=2)
'@ | & $python - $run
```

Отсутствующий ID, другой speaker/GUID или unresolved evidence требуют исследования, а не замены чужим голосом. Игрок, Narrator и неизвестные говорящие в этот NPC пилот не входят.

## Offline FMOD event render и корректировка задержки

```powershell
$native = Join-Path $game 'Rue Valley_Data/Plugins/x86_64/fmodstudio.dll'
$banks = Join-Path $game 'Rue Valley_Data/StreamingAssets'
$selected = (Get-Content -LiteralPath "$run/selection.json" -Raw -Encoding utf8 | ConvertFrom-Json).entries
foreach ($entry in $selected) {
    & $python -m dubbing.integrations.fmod.render --native $native `
        --bank "$banks/Master.bank" --bank "$banks/Voiceover.bank" `
        --bank "$banks/Voiceover.assets.bank" --guid $entry.event_guid `
        --output "$run/originals/$($entry.event_name).wav" --dry-run
}
```

После проверки плана повторить этот `foreach` без `--dry-run`. Рендер работает offline через игровую FMOD Studio ABI, `WAVWRITER_NRT`, synchronous/load/stream updates; игра не запускается. Сохраняются WAV и JSON: точный GUID, SHA256 library/banks/WAV, event_length_ms, формат, конечный playback state, сигнал и DSP tail. Все четыре события завершились штатно; один повтор дал тот же SHA256, что не доказывает детерминизм всех event graphs.

Это **рендер FMOD event timeline**, а не извлечение доказанного physical FSB sample/take. В FSB существуют альтернативные takes; совпадение имени с fragment не доказывает выбранный event sample. `physical_fsb_index_format` остаётся `unverified`. Renderer фиксирует stereo48000Hz независимо от physical sample format.

У четырёх пилотных events измерена начальная задержка3072кадра (64ms при48000Hz); render также содержит tail. Нельзя брать полную длину writer WAV за целевую длительность реплики или переносить3072 на другую конфигурацию без проверки. Prepare удаляет эту явную задержку и берёт ровно `round(event_length_ms*sample_rate/1000)` кадров; raw render сохраняется.

```powershell
& $python -m dubbing.integrations.rue_valley.prepare --selection "$run/selection.json" `
    --originals "$run/originals" --output "$run/prepared/manifest.json" `
    --render-latency-frames 3072 --target event --dry-run
& $python -m dubbing.integrations.rue_valley.prepare --selection "$run/selection.json" `
    --originals "$run/originals" --output "$run/prepared/manifest.json" `
    --render-latency-frames 3072 --target event
```

Prepare проверяет identity/hash всех источников до записи, сохраняет corrected-originals и preparation-receipt. Голосовой reference выбирается из самого длинного выбранного оригинала **того же** speaker. Это автоматический reference со статусом `needs_listening`; качество голоса и интонации не подтверждено. Контрольные символы локализации очищаются функцией `spoken_text`; исходный RU/EN и evidence остаются в манифесте.

## Синтез → fit → verify → export

Закрыть игру и проверить отсутствие другого GPU-воркера. Использовать одну очередь и отдельные output/locks. Пример настроек пилота:

```powershell
$common = @('--manifest', "$run/prepared/manifest.json", '--output', "$run/generated", `
    '--adapter', 'qwen', '--model', $model, '--device', 'cuda:0', `
    '--dtype', 'bfloat16', '--attention', 'sdpa', '--language', 'Russian', `
    '--preset', 'preview', '--timing', 'speedup', '--loudness', 'original')
& $python dub.py doctor @common --game-tools
& $python dub.py plan @common
& $python dub.py generate @common --dry-run
& $python dub.py generate @common
& $python dub.py fit @common
& $python dub.py verify @common
& $python dub.py preview @common
```

`preview` здесь управляет single/batch1, seed42/max384 синтезом; он не отключает обработку звука. Raw сохраняется отдельно. Speedup только ускоряет длинный результат с сохранением pitch и дополняет короткий тишиной. Original loudness сопоставляет RMS с corrected event render. Проверка ожидаемых IDs/формата/кадров/конечности/пика/хэшей не заменяет прослушивания русского текста и reference. Не выдавать ASR за perceptualQA. При смене fit/loudness повторять fit/verify, а не нейрогенерацию валидного raw.

```powershell
& $python -m dubbing.integrations.rue_valley.export --manifest "$run/prepared/manifest.json" `
    --selection "$run/selection.json" --generated "$run/generated" --output "$run/runtime-export" --dry-run
& $python -m dubbing.integrations.rue_valley.export --manifest "$run/prepared/manifest.json" `
    --selection "$run/selection.json" --generated "$run/generated" --output "$run/runtime-export"
```

Exporter требует `verification.json` для того же manifest, `test_tones=false`, точное равенство selected/prepared/verified IDs, speaker/reference identity, GUID и format/frame/hash каждого fitted WAV. Он создаёт только четыре allowlisted entries и явно сохраняет pilot coverage/perceptual pending/in-game false. Общий `dub.py package` создаёт ZIP WAV, но не игровой FMOD мод.

## Runtime build → stage → install → rollback

Получить [официальный BepInEx5.4.23.3 Windows x64](https://github.com/BepInEx/BepInEx/releases/tag/v5.4.23.3) и распаковать в отдельный `$loader`; не брать файлы игрового crack/DRM и не перезаписывать оригинальные DLL. Задать `$dotnet` путём к SDK executable и `$loader` каталогом распаковки. .NET8.0.408 использовался при проверке.

```powershell
$dotnet = (Get-Command dotnet -ErrorAction Stop).Source
$loader = Read-Host 'Каталог распакованного официального BepInEx5 x64'
& $dotnet --list-sdks
$integration = Get-Content integrations/unity-fmod/rue-valley.integration.json -Raw | ConvertFrom-Json
$managed = Join-Path $game $integration.managed_relative
./integrations/unity-fmod/build.ps1 -ManagedRoot $managed -LoaderRoot $loader `
    -Dotnet $dotnet -Output "$run/build"
& $python integrations/unity-fmod/manage.py stage --manifest "$run/runtime-export/manifest.json" `
    --plugin "$run/build/UniversalDubbing.Fmod.dll" --output "$run/stage" `
    --integration-config integrations/unity-fmod/rue-valley.integration.json
```

Повторить stage с `--apply`. Общий build принимает явный ManagedRoot. Он ссылается на локальные Unity/FMOD/Newtonsoft.Json assemblies без их копирования в релиз; собственный strict Newtonsoft parser заменил Unity JsonUtility после обнаруженной ошибки первого реального запуска. Runtime пишет `UD_MANIFEST` с assembly/schema/count/type, затем `UD_READY`.

```powershell
& $python integrations/unity-fmod/manage.py install --game $game --game-exe $integration.game_exe `
    --stage "$run/stage" --loader-root $loader --receipt "$run/install-receipt.json"
```

Проверить план и повторить с `--apply` при закрытой игре. Installer проверяет точный executable через Win32_Process и прекращает работу при ошибке проверки; существующий конфликтующий loader не затирается. Только собственные plugin/manifest/allowlisted WAV и необходимые официальные loader files попадают в installation plan. Уникальные backups прежнего собственного мода, прежние/новые hashes и state сохраняются в receipt.

Harmony сохраняет original event timeline, после успешной готовности replacement подавляет оригинальное аудио и воспроизводит WAV через FMOD Core в настраиваемом `bus:/Voice`. Поддерживаются exact2D GUID, stop/pause/end; `release` не считается stop для штатного fire-and-forget. 3D events сохраняют оригинал. Неизвестные events и ошибки загрузки используют original fallback. Баланс VO/master bus, skip и pause требуют фактической проверки в игре.

Фактический bootstrap Rue Valley уничтожает loader MonoBehaviour до первой сцены. Поэтому состояние озвучки живёт в отдельном обычном managed `OverrideService`, а main-thread pump вызывается из проверенного `CharacterController.Update`. Уничтожение bootstrap component не завершает service; Application.quitting выполняет cleanup. Прямые Articy callbacks и FMOD wrappers дополняют друг друга с защитой от двойного запуска. Natural context устанавливается prefix перед PlaySound и восстанавливается finalizer даже при exception/nesting. `UD_PATCH` доказывает зарегистрированные targets, а `UD_HEARTBEAT`/`UD_DIALOGUE_UI`/`UD_GAME_SOUND` — их фактическое выполнение; одного READY недостаточно.

Для безопасного **естественного** диалога следовать [RUE_VALLEY_QA.md](../integrations/unity-fmod/RUE_VALLEY_QA.md): opt-in QA save isolation, New Game/disclaimer, реальные UI fragment+event logs и запись игрового звука. Обычный/exact-Articy sound bridge явно маркируется как test и не считается естественным сюжетным flow. Не управлять input занятого пользователя без его согласования. Вернуть QA config в false после проверки.

```powershell
& $python integrations/unity-fmod/manage.py uninstall --receipt "$run/install-receipt.json"
# После проверки плана, с закрытой игрой:
& $python integrations/unity-fmod/manage.py uninstall --receipt "$run/install-receipt.json" --apply
```

Uninstall проверяет hashes всего набора до изменения файлов и отказывается затирать изменённые после установки файлы. Он восстанавливает backup собственного мода; созданные игрой logs/config/QA saves сохраняются. После установки/отката сохранять manifest, coverage/unresolved, preparation/verification/export/install receipts и SHA256. Не публиковать игровые binaries, декомпиляцию, оригинальные аудио, модель и личные пути.
