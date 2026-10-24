"""Extension boundary for game extraction, encoding, package and install adapters.

The core exports verified WAVs and IDs. A game integration owns source mapping,
codec roundtrip checks, archive paths, closed-game checks, backups and rollback.
No game archive format is assumed by the portable WAV export.
"""
