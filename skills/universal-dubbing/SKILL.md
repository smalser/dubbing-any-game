---
name: universal-dubbing
description: Prepare local game dubbing with Universal Dubbing, from game research and verified dialogue mapping to Qwen or another TTS adapter, audio validation and a reversible game pilot. Use for setting up or continuing a game voice-over project; not for text-only translation or unrelated modding.
---

# Universal Dubbing

Create a small, audible game pilot before expanding a queue. Default to local Qwen3-TTS-12Hz-1.7B-Base unless the user chooses another model. Translation of text, synthesis of speech and integration into a game are separate tasks; never imply that an audio ZIP installs itself into any game.

## Locate the project

This installed skill contains instructions, not the application, models or game tools. Do not resolve project files relative to this installed skill folder.

Use the user's Universal Dubbing checkout. Confirm it contains `dub.py`, `pyproject.toml`, `dubbing/` and `docs/PLAYBOOK.md`. If none is available, clone `https://github.com/smalser/dubbing-any-game.git` (branch `main`) into a new task workspace within the authorized scope. Do not overwrite an existing directory. If several checkouts are plausible, ask which one to use.

Run project commands from that checkout's root. Read its `AGENTS.md`, `.local.md` if present, README and `docs/PLAYBOOK.md`. Consult `python dub.py --help` and the relevant subcommand help; checked-out code wins over examples in this skill. Keep `.local.md` private. Do not use the author's machine paths as defaults.

## Select the next action

- **Setup or missing model:** use `docs/QWEN.md` for the default model and a standalone voice check; `docs/SETUP.md` for general dependencies. Installing the skill does not install Python, FFmpeg, Universal Modder or weights. Ask for model download permission only if not already granted; disclose source and size. Do not enable external TTS services or paid APIs implicitly.
- **New game:** use Universal Modder through the project's pinned `.[game]` dependency. Read `docs/INTEGRATION_GATE.md`. Establish game/version, text/audio containers, speaker/event mapping, exclusions and a reversible replacement route. A scan is not proof of mapping. Do not promise an integration exists merely because a game uses Unity, Unreal or FMOD.
- **No translated dialogue:** prepare and review the pilot translation separately, retaining original text and IDs. `--language` controls pronunciation; it does not translate text. Do not upload game text or voices to external services without authorization.
- **Verified manifest:** follow the synthesis workflow below. Unknown speakers, silence, nonverbal sounds and unresolved mappings remain explicit exclusions with reasons. Never borrow a different character's reference to fill a gap.
- **Existing output:** read its config, `status.json` and `events.jsonl`, then the STOP/cache section of `docs/CLI.md`. Changing gain or timing calls for `fit` of saved raw, not new TTS.
- **Another model:** read the adapter contract in `docs/ARCHITECTURE.md`. Select a trusted installed `module:Class` adapter; changing `model` alone cannot switch architecture. Implement an adapter only when needed for the requested model. Built-ins are `qwen` and diagnostic `mock`; mock is never a speech fallback. Custom adapters require their own preflight: doctor intentionally reports them as unverified.

## Synthesis workflow

Use a separate `work/<game>/<run>/` per experiment. Keep extracted originals, references, manifest/config, raw, fitted audio, game staging and receipts separate. A standalone Qwen voice check uses synthetic text and an authorized reference; it is not evidence of game integration.

For a game pilot, prepare 2–4 verified lines in one reachable scene. Use `docs/ARCHITECTURE.md` for the manifest schema. Preserve IDs, array order, sample rate, channels and measured target frames. Numeric IDs do not establish story order.

Create a config that includes manifest/output/model paths, adapter, language, device, dtype, attention, preset and a shared lock directory. All config paths resolve from the working directory; reference/original paths resolve from the manifest directory. Use identical synthesis settings and selection for every stage. The preview preset overrides batch size, seed and token limit; consult CLI before tuning it.

With the actual config path substituted for `CONFIG`:

```text
python dub.py doctor --config CONFIG --game-tools
python dub.py plan --config CONFIG
python dub.py generate --config CONFIG --dry-run
python dub.py generate --config CONFIG
python dub.py fit --config CONFIG
python dub.py verify --config CONFIG
python dub.py preview --config CONFIG
python dub.py package --config CONFIG
```

Proceed to synthesis only after the requested checks and input mapping pass. For another adapter, resolve its custom preflight explicitly instead of claiming doctor passed. Run one GPU worker per device unless the user deliberately chooses otherwise. Inspect processes before intervening; do not kill by name pattern, delete live locks or synthesize alongside the game on the same GPU. Do not rerun a prior experiment simply to inspect it.

Raw is retained separately. Cache validity depends on contents/settings and complete batch receipts, not just file existence. Preserve old output when changing models or incompatible cache versions. Validate finite WAVs, format, frames, peaks, selected IDs and hashes. Technical success does not prove pronunciation, voice likeness or acting quality. Give the user `listen.html` and flag excessive speedup or incomplete speech before increasing coverage.

## Game integration and completion

`package` produces `audio-export.zip`, not a game mod. Use the actual integration's codec/container and decode it back to check format and archive contents; for runtime WAV replacement, verify exact event interception, lifecycle and game audio. Read `docs/RUE_VALLEY.md` only for that specific integration, not as a universal recipe.

Respect the user's installation scope. For an authorized install, check the game is closed, preserve a uniquely named backup of the existing own mod, verify hashes after replacement and provide rollback. Never modify game originals or saves. Coordinate interactive QA when the user is using the computer. Report in-game verification only after the scene was actually exercised.

If mapping, model readiness or the replacement route is missing, stop that dependent stage and state the smallest next experiment and expected evidence. Continue independent setup work when useful. Do not make up success to complete a checklist.

Deliver config/manifest/output paths, selected coverage and exclusions, actual OS/model/device, commands and hashes where relevant, listening status, game QA status and rollback instructions. Publication is a separate request: follow `docs/RELEASING.md` and do not include game materials, models, voices, caches or credentials in public code.
