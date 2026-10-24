# Зависимости и медиа

MIT в LICENSE относится к коду этого проекта. Модели, зависимости и игровые записи имеют собственные лицензии.

- Qwen3-TTS: https://github.com/QwenLM/Qwen3-TTS — Apache-2.0 для upstream кода; отдельно проверяйте model card конкретных весов.
- Universal Modder: https://github.com/rehan-remade/universal-modder — внешний набор навыков, не включён в дистрибутив.
- NumPy: https://numpy.org/doc/stable/license.html
- SoundFile/libsndfile: https://github.com/bastibe/python-soundfile — лицензии Python-обёртки и библиотеки различаются.
- FFmpeg: https://ffmpeg.org/legal.html — условия зависят от сборки и её фильтров. Бинарники не включены.

`examples/comparison/audio/` — только локальные материалы сравнения; исходные голоса и производные записи не включаются в source ZIP. Наличие галереи не предоставляет права на публикацию этих медиа. Публикуемая версия предлагает импортировать их из собственной локальной копии. `tools/make_demo.py` создаёт синтетический тестовый сигнал без игровых файлов.
