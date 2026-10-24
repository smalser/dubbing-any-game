# Rue Valley: проверка настоящего сюжетного события

Это сценарий для root после согласованной установки. Исследующий агент игру не запускал и не менял saves. Обычный sound bridge не считается естественным диалогом.

## Безопасная изоляция сохранений

Фактический `SaveManager.SaveDirectory` возвращает `Application.persistentDataPath/Save/<SteamID>`. Все обычные autosave/quicksave/manual save и delete используют этот getter. `CreateAutoSave` хранит только один слот `AutoSave_`; поэтому новая игра без изоляции способна затереть существующий autosave. Метод `SaveManager.WriteSave` имеет overrideDirectory, но в исследованном коде он используется отдельно лишь BugReporterUI; его во время теста не открывать.

Перед QA запуском включить в собственном `BepInEx/config/local.universal-dubbing.fmod.cfg`:

```ini
[Audio]
VoiceBus = bus:/Voice

[QA]
EnableFileBridge = false
RedirectSaveDirectory = true
```

Этот opt-in Harmony prefix заменяет только результат `SaveManager.SaveDirectory` на plugin `qa-saves`. Исходные saves не переносятся и не удаляются, игровые оригиналы не меняются. Перед нажатием New Game проверить `UD_QA_SAVE_DIRECTORY ... original_saves_untouched=true` и `UD_READY`; если plugin пишет `UD_DISABLED`, прекратить тест. QA может создавать собственные saves в отдельном каталоге. Снять hashes исходного Save до/после; root уже сохранил backup. Настройки/достижения вне SaveManager этим патчем не изолируются.

Для возвращения к пользовательским saves закрыть игру, отключить RedirectSaveDirectory и перезапустить. `qa-saves` сохранить как тестовый артефакт; uninstall не удаляет созданные игрой файлы автоматически.

## Естественный путь

1. Запустить игру обычным launcher/exe. Снять screenshot главного меню и проверить loader log, READY и QA save isolation. В QA режиме Continue/Load отражают отдельный тестовый каталог.
2. В главном меню выбрать **New Game / Новая игра**. По фактическому коду `Menu.OnNewGameButtonClicked` только показывает disclaimer и отключает остальные title buttons; до подтверждения progression не начинается.
3. Подтвердить disclaimer кнопкой **Ok / ОК**. `Menu.OnDisclaimerConfirmed` вызывает установленный из `TitleScreen.NewGameInteraction` метод `InteractionActionLocal.Interact` → `StartDialogueEvent.RaiseEvent(Interactable)` → `DialoguesMenu.StartDialogue` → `Activate` → `PlayArticyGraph`. Это настоящий старт игровой ветки, а не искусственный вызов FMOD.
4. Следовать отображаемым игровым Continue/диалоговым вариантам. Положения кнопок определять по реальному screenshot; координаты не установлены. Не вызывать private HandleArticyInteractableDialogueFragment вручную: он меняет Active/UI/state, а без нормальной инициализации это неравнозначно flow.
5. В ранней **PROLOGUE / The End of First Session / Still With Me Mr. Harrow** сцене дождаться естественной реплики `DFr_5208D974` («Мистер Харроу, вы меня слушаете?»). Установленный exact GUID `{af82429b-99d5-4e6d-a3c0-21c238e6913f}` должен сработать в обычном flow. Ветвление следующих строк проверять по экрану; порядок ID не задаёт порядок выбора.
6. Сохранить screenshot с показанной репликой и запись игрового звука. В логе нужны рядом `UD_DIALOGUE_UI technical_name=DFr_5208D974 text=...` и `UD_PLAY id=72057632692673839 guid=... sha256=... context=ArticyUtils.PlaySound`. `...explicit_bridge` и `UD_BRIDGE_TEST` не засчитывать за естественный flow. Это связывает настоящий UI fragment с exact озвученным event; восприятие речи подтверждается записью/прослушиванием.
7. На следующем повторе проверить skip/continue во время речи: ожидается `UD_STOP`, голос не продолжает звучать поверх следующей реплики. Проверить pause/resume и естественное завершение `UD_END`. Выполнить проверку относительной громкости на реальном bus:/Voice.
8. Закрыть игру, сравнить исходные Save hashes с контрольными. Сохранить log/screenshots/audio, manifest/plugin hashes и QA config. После теста вернуть RedirectSaveDirectory=false, EnableFileBridge=false.

Путь до конкретной therapy сцены установлен по metadata и коду старта; фактические промежуточные экраны ещё требуют runtime наблюдения. Если старт приводит в другую сцену, следовать реальному UI/логам, не выдавать предположение за прохождение.
