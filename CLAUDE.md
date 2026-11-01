# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

A Raspberry Pi voice remote: the microphone on a WM8960 Audio HAT picks up voice commands, and a Raspberry Pi 5 forwards them to an LG TV connected over micro-HDMI. See `ARCHITECTURE.md` for the design. No code has been written yet.

## Documentation rules (from the project owner)

- With every change, update the matching sections of `README.md`: requirements, system packages, pip installations, build commands and usage. Replace the `_TBD_` placeholders as things become known.
- Record design decisions in `ARCHITECTURE.md`.
- When the owner flags a point as needing a developer note, add a row to the table in `DEVELOPER_NOTES.md`.
- `SKILLS.md` lists the roles used on the project. The primary role is embedded C developer.
- Commit changes in small steps with clear messages.

## Commands

No build, lint or test commands yet. Add them here and in `README.md` once they exist.
