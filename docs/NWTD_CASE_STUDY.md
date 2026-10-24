# Кейс: Nobody Wants to Die

Наблюдения локального исследования, не универсальная спецификация форматов. Проверявшаяся GOG-копия: game ID1484887196, build57757060854943566. Название runtime patch игры отдельно не установлено.

## Контейнеры

Unreal native Windows, IoStore `.utoc/.ucas` и V11 PAK. Исследованный индекс PAK не зашифрован, compression Oodle, mount `../../../`. Wwise metadata: 2023.1.1.8417.2904, bank version150. UE5.3.0 в plugin metadata — совместимость integration, не доказательство точного runtime patch.

Использовавшиеся инструменты: repak0.2.3, retoc0.1.5, wwiser, vgmstream, wwav и FFmpeg с Rubber Band. Они устанавливаются пользователем отдельно; binaries/исходники третьих сторон в этот репозиторий не включены.

## Articy

Legacy export получен через retoc. В исследованном export обнаружена последовательность `12 09 02 01 02 01 03`, за которой следовали12 FString: EN0, DE1, FR2, IT3, ES4, ZH5/6, JA7, PL8, RU9, KO10, PT11.

Не отбрасывать NBSP через `str.isprintable()`. Нормализовать регистр/пунктуацию только при сопоставлении, сохраняя исходные значения. FText source key и явный audio ID могут отличаться; один текстовый match не подтверждает связь.

Speaker identity сверялась с сериализованными Articy character references и проверенной сценой. Расположение поля относительно key было наблюдением этой копии, не правилом для всех Articy проектов. Не назначать голоса неизвестным записям по близости ID.

Ранний инвентарь исследования: 4 872 уникальных VO ID; 3 405 имели однозначную техническую связь text/speaker/media. Остальные включали неоднозначные/отсутствующие переводы, speaker ambiguity, development assets и неподдерживаемый источник. Эти цифры — snapshot исследования, не готовая полнота перевода и не shipped dataset.

## Итог полного локального аудита — 24 октября 2026

Учтены все 4 949 English WEM и 4 996 банков. Речевая очередь: 4 693 физических WEM, 4 728 банков (35 дополнительных bank aliases), 29 персонажей. Сохранены оригинальными 115 digital-silence, 72 nonverbal, 69 dev/test WEM — всего 256 медиа и 268 путей банков. Неучтённых физических файлов не осталось. Это результат локального аудита, а не включённый в репозиторий готовый dataset.

Дополнительное чтение сериализации Articy по точному owner позволило восстановить 1 277 официальных RU соответствий; 96 переводов подготовлены заново, внесены три точные правки текста. Фильтр «строка только из цифр» оказался неверным: такие реплики тоже могут быть речью. Для нового build весь audit нужно повторить.

Финальный PAK содержит 9 421 entry, размер 2 987 627 142 байта; SHA256 `09b67be1f4880e8c2a35ae7a99286b1f7cd5bfe34ca30bcd9d157d39adb0cefb`. Проверены roundtrip всех WEM, точные frames/rate/channels, набор путей, соответствие окончательному манифесту и SHA256 установленной копии. Перед установкой сохранён и проверен backup предыдущего собственного PAK. Полный слуховой QA не выполнен.

## Минимальная замена Wwise

Успешный runtime тест использовал bank `_0x10000050001a97d.bnk` и media `850451510.wem`. Внутренние пути:

```text
detnoir/Content/WwiseAudio/Event/English(US)/_0x10000050001a97d.bnk
detnoir/Content/WwiseAudio/Media/English(US)/850451510.wem
```

Сгенерированный fitted WAV преобразован в PCM WEM через `wwav.py convert ... --codec pcm --layout packed`. В **соответствующем простом single-source bank**, offsets которого получены wwiser:

1. Проверить исходный `ulPluginID`: поддержаны `0x40001` (Vorbis) и уже PCM `0x10001`, затем little-endian uint32 → `0x10001` (PCM). Сначала сверить единственный sourceID с выбранным media ID в XML и байтах банка.
2. `uInMemoryMediaSize` заменить размером нового WEM.
3. Остальные bytes сохранить; декодировать WEM обратно и сравнить с fitted PCM.

В sample pipeline допускается ровно один такой plugin и одно поле size. Поддержаны несколько независимых single-source банков на один WEM через `bank_aliases` (объекты с `bank_path` и необязательным `bank_xml`). Каждый банк проверяется отдельно; повторяющиеся media ID/paths между строками и пересечения bank paths запрещены. Multi-source и embedded media, другие codecs и конфликтующие голоса для одного физического WEM требуют расширения адаптера, а не слепого patch.

## PAK и проверка

Собрать только собственные replacement WEM и изменённые банки, сохраняя внутренние paths; `repak pack --version V11`. Проверить `repak list` против ожидаемого набора. Для 46 уникальных single-bank/single-media записей получилось92 entries. Это частный случай, не общее правило `2*N` для любых игр.

Установить отдельным PAK в `detnoir/Content/Paks/~mods/`, предварительно сохранив старый собственный мод. Оригинальные контейнеры не изменяются. Runtime одного replacement подтверждён игроком; оценка остальных сцен и веток остаётся за игровыми тестами.

## Источники инструментов

- [repak](https://github.com/trumank/repak)
- [retoc](https://github.com/trumank/retoc)
- [wwiser](https://github.com/bnnm/wwiser)
- [vgmstream](https://github.com/vgmstream/vgmstream)
- [wwav](https://github.com/search?q=wwav+wwise&type=repositories) — перед установкой определить конкретный upstream и проверить лицензию; binary не поставляется.
- [FFmpeg](https://ffmpeg.org/ffmpeg-filters.html)
- [Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS)
- [Qwen1.7B Base](https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base)

Ссылки указывают происхождение/документацию. Версии выше фиксируют эксперимент, а не рекомендацию автоматически скачать новейший релиз.
