# CLAUDE.md — Fish Farm Manager

> This file is read automatically at the start of every Claude Code session.
> Follow all standing instructions below without being prompted.

---

## Project summary
A Python desktop app that manages a farm of Android phones running the Roblox game Be Fish. It connects to each device via ADB, captures screenshots, reads the screen to determine game state, and takes automated actions based on what it finds. Each device runs its own independent worker loop. The goal is fully automated, unattended farm operation with per-device visibility and control.

## Standards
This project follows https://github.com/Rekot24/dev-standards
Read app-framework.md before making any architectural decisions.
If asked to do something that conflicts with those standards, flag it before proceeding.

## Architecture
- `main.py` — entry point only; wires everything together
- `bot/device_worker.py` — the main loop for each device; capture → detect → resolve state → dispatch actions
- `bot/state_machine.py` — evaluates detector results and resolves current game state
- `bot/state_rules.py` — the rules that map detection results to states
- `bot/states.py` — state constants; all state names defined here
- `bot/actions.py` — all automated actions the bot can take (taps, resets, etc.)
- `bot/device_manager.py` — manages the collection of connected devices
- `bot/config_manager.py` — loads and manages per-device configuration
- `bot/health_monitor.py` — monitors battery, temperature, ADB connection status
- `bot/farm_event_bus.py` — event system for communication between components
- `detection/detector.py` — runs template matching against captured frames
- `detection/template_bank.py` — library of reference images used for matching
- `detection/result.py` — DetectResult data shape
- `capture/` — screenshot capture from devices via ADB
- `ui/app.py` — display only; never writes to workers directly
- `config/` — settings store, per-device configs, profiles
- `tools/` — ADB utilities and general helpers
- `assets/` — template images for detection

## Device inventory
### Active farm devices
| Device | ADB ID | Roblox Account | Notes |
|---|---|---|---|
| Pixel 6 Pro | 19161FDEE005RY | 24rolla (main) | Best device, 12GB RAM, Tensor G1 |
| Pixel 8a | 43281JEKB02948 | Rekot450 | Cracked screen, 8GB RAM, 4nm — likely best thermal performance |
| Pixel 3 | 8A1X0JZ33 | 22Becca_boo | 4GB RAM, Snapdragon 845 |
| Galaxy S22 | R5CT42ZJ4JN | RollaFih | Knox locked, broken screen (1/4 black), needs keep-alive tap |
| Note 20 Ultra 5G | R5CR81W0Y7M | Rolla Jr | Knox locked bootloader |
| Galaxy S21 FE | R5CRC3M4VLM | Tide_Stalker | Knox locked, needs keep-alive tap |

### ADB paths
- HOME-PC: `C:\adb\platform-tools\adb.exe`
- JOSH-LAPTOP: `C:\phone-tools\platform-tools\adb.exe`

### Critical device notes
- **Pixels** fully respect ADB commands — no keep-alive tap needed
- **Samsung Knox** overrides ADB screen timeout settings — keep-alive tap workaround required for all Samsung devices
- All USB cables must be data cables — charge-only cables will not be detected by ADB
- `screen_off_timeout = 2147483647` (MAX_INT32 — effectively never timeout; this is a named constant, not a magic number)

## Key decisions
- [2026-08-26] Each device runs in its own independent worker loop — allows per-device control and failure isolation
- [2026-08-26] Detection uses template matching against reference images rather than OCR — more reliable for game UI elements
- [2026-09-02] Per-device feature flags chosen over profile-only control — user must be able to see and toggle every behavior per device from the UI without touching code or config files
- [2026-09-02] Health stats always displayed regardless of feature flags — visibility is non-negotiable even when health actions are disabled
- [2026-09-02] Settings store reads on every loop cycle — never cached at startup; changing a setting takes effect immediately without restart

## Tried and rejected
- [2026-08-27] Galaxy XCover Pro — GPU (Mali-G72) too weak for Roblox rendering; retired to shelf — do not re-add to active farm
- Do not attempt to make Samsung Knox devices behave like Pixels via ADB — Knox intentionally blocks these commands; the keep-alive tap is the correct workaround

## Planned work (see ROADMAP.md for full list)
- Per-device feature flag UI — checkboxes for every detector, action, and health response per device
- Profile system — save/load named sets of feature flags per device
- Separate debug and logging layers — currently combined; needs to be split per dev-standards Layer 7
- constants.py — magic numbers exist in codebase (screen_off_timeout, thresholds); need to be extracted
- CLAUDE.md standing instructions compliance audit — codebase predates these standards

## Current state
- Working: ADB connection, screenshot capture, template detection, state machine, basic actions, health monitoring, UI display
- In progress: Per-device feature flag system, profile save/load
- Known broken: Detection loop reliability — multiple behaviors running simultaneously without individual toggles makes isolation and debugging difficult

## Session log
### 2026-09-02
- Audit session initiated — codebase reviewed against dev-standards
- AUDIT.md and ROADMAP.md generated
- Modified: bot/device_manager.py, bot/device_worker.py, ui/app.py
- Decision made: per-device feature flags with live checkbox UI is the correct architecture
- Decision made: profiles are named snapshots of feature flag state, not the source of defaults
- CLAUDE.md created with full project context

---

## Standing instructions

These apply every session without being included in the prompt:

1. Read this file fully before touching any code.
2. Read app-framework.md from https://github.com/Rekot24/dev-standards before any architectural work.
3. Before building anything, explain what you are going to do and why. Wait for confirmation before proceeding.
4. Flag anything that conflicts with dev-standards before proceeding — do not comply silently.
5. No magic numbers or magic strings — all named values go in `config/constants.py` with a comment explaining what they mean and where they came from.
6. No raw print statements — all output goes through the logger.
7. Every function gets a docstring before implementation is written.
8. All error handling follows the two-mode pattern: fail loudly in development, fail gracefully in production.
9. No feature runs unconditionally — every feature checks its enabled flag in the settings store before doing anything.
10. Samsung Knox devices require keep-alive tap — do not attempt to fix this via ADB settings commands.
11. Health stats are always displayed in the UI regardless of what feature flags are enabled or disabled.
12. At the end of every session, before closing:
    - Add a dated entry to the session log above summarizing what was done and decided
    - Update current state (working / in progress / known broken)
    - Add any new architectural choices to key decisions
    - Add anything tried and abandoned to tried and rejected
    - Commit the updated CLAUDE.md as the final commit of the session with message: `docs: update CLAUDE.md session log [YYYY-MM-DD]`
