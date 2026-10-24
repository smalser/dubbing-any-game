# Unity Mono / FMOD exact event override

Адаптер проверен компиляцией с локальными assemblies Rue Valley Unity 2022.3.62f2, FMODUnity и официальным BepInEx 5.4.23.3 x64. Проверка внутри игры выполняется отдельно; сборка DLL сама по себе не доказывает работоспособность или качество речи.

Реальный путь Rue Valley: `BackgroundDialogueInstanceUI.PlayVoiceOver` и основной диалог вызывают `ArticyUtils.HandleSoundEffectsFeature`; приватный `ArticyUtils.PlaySound` читает `SoundEffect.Template.SoundEffectFeature.FmodId`, создаёт FMOD event и вызывает `start`. `StopVoiceOverSound`/`StopSound` вызывают `stop`. Реальный `AmbienceAudio` использует `bus:/Voice` для паузы/громкости. Декомпиляция хранится только в приватной work-области.

Harmony перехватывает managed wrappers `FMOD.Studio.EventInstance.start/stop/setPaused`. Для exact allowlist GUID создаёт WAV sound через FMOD Core, маршрутизирует в `bus:/Voice`, сохраняет volume исходного instance и только после успешного запуска replacement устанавливает исходному событию volume=0. Оригинальный event продолжает управлять своим timeline/lifecycle. Остальные GUID остаются оригинальными. Ошибка загрузки/хэша отключает мод; ошибка playback оставляет оригинальное аудио. 3D события сейчас намеренно пропускаются с `UD_SKIP_3D`: этот вертикальный срез поддерживает 2D dialogue, а не пространственную озвучку.

`release` не останавливает replacement: FMOD штатно вызывает release сразу после start для one-shot; остановка на release обрывала бы валидную речь. Явный `stop`, pause и уничтожение plugin останавливают/паузят replacement. Завершённый звук освобождается в Update. Bus routing сохраняет VO/master mixer automation и pause; in-game проверка фактического баланса обязательна.

Манифест `schema_version: 1`, `entries`: каждый элемент содержит `id`, `event_guid` (стандартный UUID), `wav` (относительно манифеста), `sha256`. Только конечные разрешённые PCM16 mono/stereo WAV проходят staging. Имена/порядок/coverage исходного экспортера сохраняются. Существующие игровые банки, DLL и saves адаптер не меняет.

Сборка без NuGet restore, с установленным .NET SDK (runtime недостаточно):

```powershell
./integrations/unity-fmod/build.ps1 -ManagedRoot $managed -LoaderRoot $loader -Dotnet $dotnet -Output $build
```

Также включён csproj для стандартного SDK build с `ManagedRoot`/`LoaderRoot`; для него могут понадобиться .NET Framework reference assemblies. `build.ps1` использует именно managed reference assemblies локальной игры и потому не требует reference-pack загрузки.

`rue-valley.integration.json` хранит конкретные defaults игры: executable, относительный Managed и bus. Общий build требует явный ManagedRoot. В staging можно передать `--integration-config integrations/unity-fmod/rue-valley.integration.json`: его voice_bus сохраняется в export manifest. Runtime `Audio.VoiceBus` в BepInEx config переопределяет manifest; базовое значение `bus:/Voice`.

Каждая команда по умолчанию выводит план. `--apply` выполняет изменения:

```powershell
python integrations/unity-fmod/manage.py stage --manifest $exportManifest --plugin $pluginDll --output $newStage
python integrations/unity-fmod/manage.py stage --manifest $exportManifest --plugin $pluginDll --output $newStage --apply
python integrations/unity-fmod/manage.py install --game $game --game-exe "Rue Valley.exe" --stage $newStage --loader-root $loader --receipt $newReceipt
python integrations/unity-fmod/manage.py install --game $game --game-exe "Rue Valley.exe" --stage $newStage --loader-root $loader --receipt $newReceipt --apply
python integrations/unity-fmod/manage.py uninstall --receipt $newReceipt
python integrations/unity-fmod/manage.py uninstall --receipt $newReceipt --apply
```

Installer проверяет закрытую игру по точному executable path через Win32_Process; переносит только собственный plugin/manifest/allowlisted WAV и файлы официального loader (core, winhttp.dll, doorstop config/version). Конфликтующий существующий loader отклоняется. Предыдущие собственные файлы сохраняются в уникальную backup-папку, receipt содержит прежние/новые SHA256. Uninstall сначала проверяет весь набор, отказывается затирать изменённые после установки файлы и восстанавливает backup. Созданные BepInEx logs/config/cache остаются; оригинальные archives и saves не затрагиваются. При аварии установки receipt имеет state=installing и содержит каждый начатый перенос для восстановления.

Проверка: `python -m unittest discover -s tests -p test_unity_fmod.py`.

В `BepInEx/LogOutput.log` ожидаются `UD_READY`, затем `UD_PLAY id=... guid=... sha256=... channel=... context=ArticyUtils.PlaySound` при реальном диалоге; `UD_STOP` при пропуске/отмене, `UD_END` после завершения. `context=other_or_explicit_test` не является доказательством игрового диалога. Подтверждение perceptual QA требует прослушивания/записи игры.

Опциональный file bridge отключён по умолчанию. Для проверки FMOD plumbing включить `QA.EnableFileBridge` в BepInEx config и записать exact UUID из allowlist в plugin-папку `test-event.txt`. Update читает и удаляет запрос на главном Unity потоке, запускает настоящий FMOD event, пишет `UD_BRIDGE_TEST`. Bridge не вводит текст/клавиши, не открывает saves и не заменяет проверку реального диалога. Не оставлять его включённым в релизной конфигурации.

Для проверки реального Articy sound object добавьте экспортированное exact `sound_id` в entry и запишите `sound:<id>` в тот же файл. Bridge получает объект по ulong ID из фактической `ArticyDatabase`, повторно сверяет его `Template.SoundEffectFeature.FmodId` с allowlist, вызывает реальный `ArticyUtils.PlaySound` и явно пишет `UD_DIALOGUE_BRIDGE`/`context=ArticyUtils.PlaySound_explicit_bridge`. Он не продвигает диалог, не меняет сцену и не пишет сохранения. Это проверка подлинного игрового sound pipeline, а не подтверждение естественного сюжетного прохождения.

Естественный UI/flow test и изоляция saves описаны в [RUE_VALLEY_QA.md](RUE_VALLEY_QA.md). Read-only observer пишет `UD_DIALOGUE_UI technical_name=... text=...` при фактическом `DialoguesMenu.HandleArticyInteractableDialogueFragment`, независимо от event override. Он не вызывает игровой метод и не меняет progression.

Реальная Rue Valley уничтожает BepInEx bootstrap MonoBehaviour при старте. Production state вынесен в plain managed `OverrideService`; компонент `Plugin` только инициализирует его. Harmony callbacks и `CharacterController.Update` продолжают работать независимо от Unity lifetime; cleanup выполняется на Application.quitting. PlaySound prefix/finalizer задают natural context до FMOD wrapper start, а postfix повторно подтверждает actual Articy sound_id/GUID и исключает двойной запуск. Первый естественный fragment/event был подтверждён в diagnostic runtime; окончательный managed-service build требует повторного in-game QA.

Manifest parser uses Newtonsoft.Json from the game Managed folder (Rue Valley ships version13). Build references it without copying/redistributing game binaries. Startup UD_MANIFEST logs parser assembly/schema/count/type before READY. Actual parser harness ManifestCheck.cs can be compiled with Manifest.cs and the same Newtonsoft reference; tests/test_unity_fmod_manifest.py runs its malformed/duplicate/path cases when UNITY_FMOD_MANIFEST_CHECK and UNITY_FMOD_DOTNET environment variables point to the private harness and runtime.
