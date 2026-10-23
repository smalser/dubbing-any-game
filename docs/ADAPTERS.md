# Адаптеры и перенос на другую игру

`dub.py` — reference implementation для Windows и исследованного Wwise/Unreal пути. CPU fit/demo переносимы, но полный pipeline не универсален.

| Часть | Можно переиспользовать | Требуется новая проверка |
|---|---|---|
| Manifest | IDs, text, speaker, status/blockers, scene/order | Извлечение и точное соответствие данным игры |
| Qwen | Local model, Russian, caching, job metadata | Голоса, ограничения языка, VRAM, длина вывода |
| CPU audio | Tempo, trim, LUFS, padding | Окна событий, channels/rate, допустимость переменной длины |
| Wwise | Проверка bytes/offsets, roundtrip | Версия bank, codec, streaming, shared/embedded media |
| Unreal | Isolated stage, expected path list | PAK version/mount, IoStore overrides и правила загрузки |
| Install | Backup, hash, explicit action | Путь mods, процесс игры, совместимость overrides |

В `dub.py` заменить `game_closed`, путь исходного контейнера в `prepare`, правила bank/media mapping. В `audio_pipeline.py` заменить `build_package`/`install_package`, если формат другой. Не убирать guards ради прохождения неподдерживаемого bank.

Исторический extractor Articy не включён как якобы готовый импортёр: он зависел от локального legacy export и промежуточных карт исследования. [Кейс](NWTD_CASE_STUDY.md) сохраняет обнаруженные признаки; генератор полного manifest для новой установки нужно проверять отдельно. Репозиторий намеренно не содержит готовой карты диалогов.

Для нового адаптера сначала нужен тест одного replacement в реальной игре, затем небольшой набор с ветвлением. CPU-тесты проверяют алгоритм, а не путь загрузки assets игрой.
