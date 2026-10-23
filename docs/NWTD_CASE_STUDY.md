# Кейс: Nobody Wants to Die

Наблюдения локального исследования, не универсальная спецификация форматов. Проверявшаяся GOG-копия: game ID1484887196, build57757060854943566. Название runtime patch игры отдельно не установлено.

## Контейнеры

Unreal native Windows, IoStore `.utoc/.ucas` и V11 PAK. Исследованный индекс PAK не зашифрован, compression Oodle, mount `../../../`. Wwise metadata: 2023.1.1.8417.2904, bank version150. UE5.3.0 в plugin metadata — совместимость integration, не доказательство точного runtime patch.

Использовавшиеся инструменты: repak0.2.3, retoc0.1.5, wwiser, vgmstream, wwav и FFmpeg с Rubber Band. Они устанавливаются пользователем отдельно; binaries/исходники третьих сторон в этот репозиторий не включены.

## Articy

Legacy export получен через retoc. В исследованном export обнаружена последовательность `12 09 02 01 02 01 03`, за которой следовали12 FString: EN0, DE1, FR2, IT3, ES4, ZH5/6, JA7, PL8, RU9, KO10, PT11.

Не отбрасывать NBSP через `str.isprintable()`. Нормализовать регистр/пунктуацию только при сопоставлении, сохраняя исходные значения. FText source key и явный audio ID могут отличаться; один текстовый match не подтверждает связь.

Speaker identity сверялась с сериализованными Articy character references и проверенной сценой. Расположение поля относительно key было наблюдением этой копии, не правилом для всех Articy проектов. Не назначать голоса неизвестным записям по близости ID.

Инвентарь исследования: 4 872 уникальных VO ID; 3 405 имели однозначную техническую связь text/speaker/media. Остальные включали неоднозначные/отсутствующие переводы, speaker ambiguity, development assets и неподдерживаемый источник. Эти цифры — snapshot исследования, не готовая полнота перевода и не shipped dataset.

## Минимальная замена Wwise

Успешный runtime тест использовал bank `_0x10000050001a97d.bnk` и media `850451510.wem`. Внутренние пути:

```text
detnoir/Content/WwiseAudio/Event/English(US)/_0x10000050001a97d.bnk
detnoir/Content/WwiseAudio/Media/English(US)/850451510.wem
```

Сгенерированный fitted WAV преобразован в PCM WEM через `wwav.py convert ... --codec pcm --layout packed`. В **соответствующем простом single-source bank**, offsets которого получены wwiser:

1. Проверить старый `ulPluginID == 0x40001` (Vorbis), затем little-endian uint32 → `0x10001` (PCM).
2. `uInMemoryMediaSize` заменить размером нового WEM.
3. Остальные bytes сохранить; декодировать WEM обратно и сравнить с fitted PCM.

В sample pipeline допускается ровно один такой plugin и одно поле size. Multi-source, embedded/shared media и другие codecs требуют расширения адаптера, а не слепого patch.

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
