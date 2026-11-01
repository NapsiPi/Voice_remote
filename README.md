# Voice Remote

A Raspberry Pi voice remote for a TV. A microphone on an audio HAT picks up spoken
commands, the Pi recognises them, and the matching control command goes to the TV
over the micro-HDMI connection.

> Status: project setup. No code yet. The sections below get filled in as features
> land.

## Requirements

### Hardware
| Part | Model | Role |
|------|-------|------|
| Single-board computer | Raspberry Pi 5 | Runs voice capture, recognition and TV control |
| Audio HAT | WM8960 Audio HAT (WM8960 codec, on-board microphones) | Microphone input to the Pi |
| TV | LG (exact model TBD) | Target device, connected to the Pi by micro-HDMI |
| Cable | Micro-HDMI to HDMI | Pi 5 to TV link |

### Software
- Raspberry Pi OS for the Raspberry Pi 5 (version: TBD)
- WM8960 HAT driver / device-tree overlay (setup steps: TBD)
- Other software: TBD

## Installation

### System packages
_TBD_

### pip packages
_TBD_

## Build

_TBD_

## Usage

_TBD_

## Documentation

- [ARCHITECTURE.md](ARCHITECTURE.md): system design and data flow
- [DEVELOPER_NOTES.md](DEVELOPER_NOTES.md): running notes and reminders for developers
- [SKILLS.md](SKILLS.md): skills and roles used on this project
