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
- `bot/app_logger.py` — persistent logging (Layer 7): rotating `logs/app.log` + always-on `logs/errors.log`, one unified `log(msg, level)` call site
- `bot/health_monitor.py` — monitors battery, temperature, ADB connection status
- `bot/farm_event_bus.py` — event system for communication between components
- `detection/detector.py` — runs template matching against captured frames
- `detection/template_bank.py` — library of reference images used for matching
- `detection/result.py` — DetectResult data shape
- `capture/` — screenshot capture from devices via ADB
- `ui/app.py` — display only; never writes to workers directly
- `config/settings.py` — global app settings (`config/settings.json`)
- `config/devices.py` — per-device configuration (`config/devices.json`)
- `config/profiles.py` — behavior/logic profiles, read-only at runtime (`config/profiles/*.yaml`)
- `config/paths.py` — shared path resolution used by the three above
- `tools/` — ADB utilities and general helpers
- `assets/` — template images for detection

(`bot/config_manager.py` no longer exists — split into the four `config/*.py` files above as of the 2026-09-02 Phase 2 pass. If you're looking for settings/devices/profiles loading code, it's there now, not in `bot/`.)

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
- [2026-09-02] Persistent logging (Layer 7) built on stdlib `logging` with `RotatingFileHandler`, wrapped in one unified `app_logger.log(msg, level)` call site, rather than hand-rolled file writing — reuses proven rotation/formatting instead of reinventing it
- [2026-09-02] `logs/errors.log` always records ERROR/CRITICAL regardless of the `logging.enabled` master switch — a failure record must not depend on the same switch that silences routine noise
- [2026-09-02] UI-triggered actions on a worker go through public `DeviceManager` methods (`is_device_running`, `trigger_end_run`) backed by public `DeviceWorker` methods (`request_manual_end_run`) — the UI must never call a worker's private methods or reach into `DeviceManager`'s private worker dict, per the standard's non-negotiable UI rule
- [2026-09-02] `config_manager.py` split into `config/settings.py` / `config/devices.py` / `config/profiles.py`, with a new `config/paths.py` holding the path-resolution helpers all three share — added beyond what ROADMAP.md's Phase 2 wrote down, specifically to avoid three copies of the same `_project_root()`-style functions after the split
- [2026-09-02] Every constant in `config/constants.py` (Phase 3 onward) is tagged `[TUNABLE]` or `[INTERNAL]` in its comment, not just explained in prose — `[TUNABLE]` means user-adjustable, will get a settings-dialog row and a config-store override; `[INTERNAL]` means it needs a name but has no user-facing meaning and never surfaces in the UI. Makes the later UI-surfacing pass mechanical instead of a fresh judgment call per constant.
- [2026-09-02] Surfacing `[TUNABLE]` constants.py values in the Settings dialog is its own ROADMAP phase (Phase 12), separate from Phase 11's per-device feature-flag checkboxes — they're different UI surfaces (one global dialog vs. one panel per device) with different dependencies (Phase 3 vs. Phase 6+8), even though both were originally lumped under "Phase 11 — settings UI" in conversation
- [2026-09-02] `config/constants.py` (instruction 5) is scoped to app-wide/config-meaningful magic numbers — not literally every numeric literal anywhere. Purely local UI layout facts (e.g. `ui/app.py`'s resize-math constants) stay as module-level constants next to the code that uses them, rather than being centralized alongside ADB timeouts and health thresholds
- [2026-09-02] `bot/config_manager.py` deleted outright rather than kept as a re-export shim — no consumers of it exist outside this repo, so a shim would only be a second source of truth to keep in sync for no benefit
- [2026-09-02] `[TUNABLE]` constants get a live config-dataclass field now (Phase 3) only where the call site already holds a live `Settings`/`HealthMonitor` reference — `HealthConfig` (device_worker.py's settle/poll delays) and the new `AdbConfig` (health_monitor.py, device_manager.py). `bot/actions.py`'s free functions and the three standalone Tkinter tool dialogs (image_capture_tool.py, coordinate_finder.py, add_device_dialog.py) use the same named constants as static defaults instead — they don't currently receive a `Settings` object at all, and threading one through ~15 call sites is a bigger change than this phase's scope. Recorded in AUDIT.md §4 as a deliberate, visible boundary, not a silent gap.
- [2026-09-02] `_max_unknown_s` (crash-detection timeout) removed as a cached instance attribute — `_check_crash_timeout()` now reads `self.settings.health.crash_detect_after_s` live at the point of use, so a settings change takes effect immediately rather than requiring the worker to restart, consistent with every other live setting in the app
- [2026-09-02] The debug layer (Layer 3) is strictly additive to the logging layer (Layer 7) — every existing INFO/WARNING/ERROR log from Phase 1 stays exactly as-is, always on. Debug categories (`log_detections`, `log_state_changes`, `log_actions`, `log_health`, `log_config_reads`, `screenshot_on_event`) only ever add supplementary, opt-in detail on top. Chosen over reclassifying the existing lines to be DEBUG-gated, which the standard's own example arguably supports but would mean those lines vanish from default logs the moment `debug.enabled` defaults to `False` — confirmed with user before implementing.
- [2026-09-02] `SettingsDialog._save()` uses `dataclasses.replace()` off the originally-loaded `Settings`, not fresh `HealthConfig(...)`/`DebugConfig(...)`/`LoggingConfig(...)` construction — found and fixed a real bug where every config field the dialog doesn't expose (all of `AdbConfig`, `HealthConfig`'s Phase 3 settle/poll fields) was silently resetting to its dataclass default on every Save, discarding whatever was actually loaded from disk. Applies as a pattern to any future dialog that edits a subset of a larger config object.
- [2026-09-02] `bot/app_logger.py`'s `LoggingConfig`/`DebugConfig` imports moved behind `TYPE_CHECKING` to let `config/settings.py` import `app_logger` (Phase 5, routing its own `print()`s) without a circular import — safe since neither type is ever constructed or isinstance-checked in `app_logger.py`, only attribute-read. General pattern for this codebase: `config/*.py` needing `app_logger` is expected to keep happening, and this is the fix each time, not a one-off.
- [2026-09-02] Free functions and classes with no natural `log_fn`/instance to route through (the three `config/*.py` load functions, `capture/scrcpy_socket.py`, `capture/adb_screencap.py`) call `app_logger.log()` directly rather than being threaded a `log_fn` parameter — it's already the module-level single entry point, so there's nothing a passed-in parameter would add except indirection. Capture-backend logs reach the file/console logger this way but not the UI panel; making them UI-visible would need a `log_fn` threaded through `make_backend()`, which is a bigger change than "route through the logger" — logged as a scope boundary in Planned work, not fixed silently.
- [2026-09-02] Before moving any profile-YAML behavior flag (Phase 6), traced every actual read of `profile.behaviors` in the codebase first — found most of the block was already dead code (`auto_farm_reset`/`end_run_reset` stale duplicates of `TimerConfig`; `rejoin_on_kick`/`rejoin_source`/`auto_rejoin`/`cascade_reset_on_lead_reset`/`move_to_private_on_revive_exhausted` never read anywhere). Only migrated what was real; deleted the rest along with the now-empty `behaviors:` block and `ProfileConfig.behaviors` field entirely, rather than migrating dead config forward out of caution.
- [2026-09-02] `cascade_reset_enabled`/`cascade_reset_delay_after_lead_s` landed on `TimerConfig`, not a new standalone class — they're the same "reset cycle" concept the existing timer fields already cover, and the code reading them lives in `device_worker.py`'s Timer logic section, not its death-handling code. The other five moved flags (death/revive/eaten-by) got a new `DeathBehaviorConfig` on `DeviceConfig` instead, since they're a genuinely distinct concern.
- [2026-09-02] Migrating `devices.json` entries that predate the Phase 6 fields is done via profile-aware defaults computed inside `load_devices()` (e.g. `eaten_by_detection_enabled` defaults to `is_lead`) — not by hand-editing the real `devices.json`. Preserves exact current behavior for every existing device with zero risk of a manual-edit mistake; once a device is saved through a future UI (Phase 11), explicit values take over.

## Tried and rejected
- [2026-08-27] Galaxy XCover Pro — GPU (Mali-G72) too weak for Roblox rendering; retired to shelf — do not re-add to active farm
- Do not attempt to make Samsung Knox devices behave like Pixels via ADB — Knox intentionally blocks these commands; the keep-alive tap is the correct workaround
- [2026-09-02] A `ui_sink` callback-registration layer in `app_logger.py`, for forwarding log calls to the UI — added, then removed same session. Every log call already flows through `App.log()`, which handles the file logger and the UI queue directly; the extra indirection had no second caller. Don't re-add without an actual need for something other than `App.log()` to reach the UI.

## Planned work (see ROADMAP.md for full list)
- Per-device feature flag UI — checkboxes for every detector, action, and health response per device, including `DeviceConfig.death_behavior` and `TimerConfig.cascade_reset_*` added in Phase 6 (ROADMAP Phase 11)
- Profile system — save/load named sets of feature flags per device, now unblocked by Phase 6 (ROADMAP Phase 8)
- Dev vs. production error-handling mode (ROADMAP Phase 7) — next up
- Surface `[TUNABLE]` constants in the Settings dialog (ROADMAP Phase 12) — the constants themselves are named and live in `config/constants.py` as of Phase 3; the actual UI rows are still pending, along with settings-store threading for `bot/actions.py` and the standalone tool dialogs (see AUDIT.md §4)
- `DebugConfig.save_failed_captures` exists and is UI-exposed but is never actually read anywhere — noticed during Phase 4, not fixed (different gap than debug-layer plumbing; belongs with an actual capture-failure-handling feature)
- Capture-backend logs (`capture/scrcpy_socket.py`, `capture/adb_screencap.py`) reach the file/console logger as of Phase 5 but not the UI panel — would need a `log_fn` threaded through `make_backend()`; noted as a scope boundary, not fixed
- CLAUDE.md standing instructions compliance audit — codebase predates these standards

## Current state
- Working: ADB connection, screenshot capture, template detection, state machine, basic actions, health monitoring, UI display, persistent logging (rotating `logs/app.log` + always-on `logs/errors.log`, real per-message levels), config loading/saving/validation split into `config/settings.py` / `config/devices.py` / `config/profiles.py` / `config/paths.py`, every magic number named and tagged in `config/constants.py`, debug layer (master switch + 6 categories, additive to normal logging, all exposed in the Settings dialog), no raw `print()` calls left in application logic (only the three deliberate logging-mechanism fallbacks), device behavior flags (`death_behavior`, `cascade_reset_*`) live in `DeviceConfig`/`TimerConfig` and re-read every cycle instead of loaded once from static profile YAML
- In progress: Per-device feature flag UI, profile save/load — both now unblocked by Phase 6; working through ROADMAP.md's standards-compliance phases (Phase 0, 1, 2, 3, 4, 5, 6 done, Phase 7 — dev vs. production error-handling mode — is next)
- Known broken: Detection loop reliability — multiple behaviors running simultaneously without individual toggles makes isolation and debugging difficult

## Session log
### 2026-09-02
- Audit session initiated — codebase reviewed against dev-standards
- AUDIT.md and ROADMAP.md generated
- Modified: bot/device_manager.py, bot/device_worker.py, ui/app.py
- Decision made: per-device feature flags with live checkbox UI is the correct architecture
- Decision made: profiles are named snapshots of feature flag state, not the source of defaults
- CLAUDE.md created with full project context

### 2026-09-02 — Phase 0 + Phase 1 (ROADMAP.md)
- Phase 0 (quick wins): added README.md; fixed the UI→worker boundary violation flagged in the audit (`DeviceManager.is_device_running()` / `trigger_end_run()` added, backed by a new `DeviceWorker.request_manual_end_run()`). Fixing it surfaced a live bug: the old direct call `worker._execute_end_run()` passed no `results` argument to a method that required one, so the manual "End Run" button threw `TypeError` on every click — fixed as part of the same change.
- Phase 1 (Layer 7 logging): built the persistent logging layer end to end. New `bot/app_logger.py` (unified `log(msg, level)` call site, stdlib `logging` + `RotatingFileHandler`); new `LoggingConfig` on `Settings`; `logs/app.log` (rotating) and `logs/errors.log` (errors/criticals only, always on) confirmed with a functional smoke test (level filtering, always-on errors.log even with `enabled=False`). All ~60 existing `_log()` call sites in `device_worker.py` and `device_manager.py` reclassified with real levels — not left at a default. Settings dialog got a new Logging section; `DeviceManager.reload_settings()` reconfigures the logger live (no restart). `logs/` added to `.gitignore`.
- Audit follow-up: user flagged a "no magic numbers" rule ahead of it landing in `app-framework.md` — audited the codebase against it, found the same ADB timeout literal duplicated independently 8+ times plus several other unnamed timeouts/thresholds/layout constants; recorded as AUDIT.md section 4 and inserted as ROADMAP.md Phase 3.
- Modified: bot/device_worker.py, bot/device_manager.py, bot/config_manager.py, main.py, ui/app.py, ui/settings_dialog.py, .gitignore, AUDIT.md, ROADMAP.md. Added: README.md, bot/app_logger.py.

### 2026-09-02 — Phase 2 (ROADMAP.md)
- Split `bot/config_manager.py` (392 lines, three responsibilities) into `config/settings.py`, `config/devices.py`, `config/profiles.py` — same class/function names, just relocated. Added `config/paths.py` (not in the original ROADMAP.md wording) so the three don't each duplicate the same five path-resolution helpers. `bot/config_manager.py` deleted outright, no shim — confirmed via user decision, no consumers exist outside this repo.
- Repointed all 10 files that imported from `bot.config_manager`: main.py, ui/app.py, ui/settings_dialog.py, ui/device_settings_dialog.py, ui/add_device_dialog.py, tools/image_capture_tool.py, bot/device_worker.py, bot/device_manager.py, bot/health_monitor.py, bot/app_logger.py.
- Verified with a full-repo `py_compile` pass and a functional smoke test: imported every touched module, then ran `load_settings()` / `load_devices()` / `load_profile("lead_private")` against the real config files on disk (6 configured devices, 1 lead profile) with no errors.
- Updated README.md, AUDIT.md, and ROADMAP.md to point at the new file locations (including the stray-`print()` line numbers, which moved with the split but are still unfixed — that's Phase 5).
- Modified: main.py, ui/app.py, ui/settings_dialog.py, ui/device_settings_dialog.py, ui/add_device_dialog.py, tools/image_capture_tool.py, bot/device_worker.py, bot/device_manager.py, bot/health_monitor.py, bot/app_logger.py, README.md, AUDIT.md, ROADMAP.md, CLAUDE.md. Added: config/__init__.py, config/paths.py, config/settings.py, config/devices.py, config/profiles.py. Deleted: bot/config_manager.py.

### 2026-09-02 — standing instruction 5 refined, ahead of Phase 3
- User added the `[TUNABLE]`/`[INTERNAL]` tagging requirement to instruction 5 before Phase 3 started, plus the UI-layout-constants exception (both now in the instruction text itself, not just prose).
- Surfaced and resolved a scope mismatch: instruction 5's UI-surfacing pass was going to target "ROADMAP Phase 11," but Phase 11 turned out to already be a different, pre-existing thing (per-device feature-flag checkboxes). Split into a new Phase 12 specifically for surfacing `[TUNABLE]` constants in the global Settings dialog, with its own dependency (Phase 3) — see key decisions above.
- Modified: CLAUDE.md, ROADMAP.md.

### 2026-09-02 — Phase 3 (ROADMAP.md)
- Created `config/constants.py`: every genuinely bare/unnamed literal cataloged in AUDIT.md §4, each tagged `[TUNABLE]` or `[INTERNAL]`. ADB timeouts split into three tiers (`ADB_QUICK_TIMEOUT_S`/`ADB_DEFAULT_TIMEOUT_S`/`ADB_LAUNCH_TIMEOUT_S`, plus screencap/reconnect variants) rather than collapsed to one value, since the current literals differ for real reasons.
- Added a new `AdbConfig` to `config/settings.py`, and six new fields to `HealthConfig` (crash/battery/temp settle and poll delays, thermal-throttle multiplier) — live-wired for call sites that already hold a `Settings` reference (`HealthMonitor`, `DeviceManager`, `DeviceWorker`). `bot/actions.py` and the three standalone Tkinter tool dialogs use the same constants as static defaults, not live settings — flagged explicitly as a scope boundary, not a silent gap (see key decisions).
- Removed `_max_unknown_s` as a cached instance attribute on `DeviceWorker`; crash-detection timeout now reads live from `self.settings.health.crash_detect_after_s`.
- Deduped the `0.82` template-confidence default: `detection/detector.py`'s four functions and `Settings.template_confidence_default` now all reference one `DEFAULT_TEMPLATE_CONFIDENCE` constant.
- Named the UI resize-math constants locally in `ui/app.py` (not `config/constants.py`), per the refined instruction 5.
- Found and fixed four more unnamed literals in `capture/scrcpy_socket.py` beyond what the original audit called out, while already in that file for the two retry sleeps.
- Verified with a full-repo compile pass, a functional smoke test (Settings defaults, detector.py/Settings sharing the same confidence-default object via `inspect.signature`, save/load round-trip with the new fields, HealthMonitor's live `adb_cfg` wiring), and a `DeviceWorker` end-to-end construction test confirming `_max_unknown_s` is gone and `_health_monitor.adb_cfg is settings.adb`.
- Modified: bot/device_worker.py, bot/device_manager.py, bot/actions.py, bot/health_monitor.py, config/settings.py, detection/detector.py, capture/adb_screencap.py, capture/scrcpy_socket.py, ui/app.py, ui/add_device_dialog.py, tools/coordinate_finder.py, tools/image_capture_tool.py, README.md, AUDIT.md, ROADMAP.md, CLAUDE.md. Added: config/constants.py.

### 2026-09-02 — Phase 4 (ROADMAP.md)
- Expanded `DebugConfig` with the master `enabled` switch (default `False`) and five new categories (`log_detections`, `log_actions`, `log_health`, `log_config_reads`, `screenshot_on_event`), alongside the pre-existing `log_state_changes`.
- Resolved a real tension in the standard before implementing (Layer 7's "state changed" as always-on INFO vs. Layer 3's `log_state_changes` as a gated debug category) by confirming with the user: additive, not overlapping. See key decisions.
- Central `debug()` function added to `bot/app_logger.py`; thin `_debug(category, msg)` wrappers added to `DeviceWorker` and `DeviceManager`, delegating through their existing `_log()`.
- Wired six call sites: `log_detections`/`log_state_changes` after detector runs (`_format_results()` helper added), `log_health` after every health check, `log_actions` at the top of `_dispatch()`, `log_config_reads` in `DeviceManager.reload_settings()`/`reload_device_configs()`, `screenshot_on_event` extending death-screenshot capture to private mode (previously public-mode-only, as a business feature).
- All new `DebugConfig` fields exposed as checkboxes in the Settings dialog (flat, grouped under the existing "Debug" section — not a true collapse/expand widget).
- Found and fixed a real bug while wiring the new checkboxes: `SettingsDialog._save()` was constructing fresh config objects from only its exposed fields, silently resetting every Phase-3-added field the dialog doesn't have a row for. Fixed with `dataclasses.replace()` — see key decisions.
- Noticed but didn't fix: `DebugConfig.save_failed_captures` is UI-exposed but never actually read by any code path — different gap than this phase's scope, added to Planned work.
- Verified with a full-repo compile pass, a functional smoke test (`app_logger.debug()` gating logic, `DeviceWorker`/`DeviceManager` `_debug()` end-to-end, `_format_results()`), and a real-Tkinter `SettingsDialog` test confirming the `dataclasses.replace()` fix actually preserves dialog-unexposed field values through a save.
- Modified: config/settings.py, bot/app_logger.py, bot/device_worker.py, bot/device_manager.py, ui/settings_dialog.py, AUDIT.md, ROADMAP.md, CLAUDE.md.

### 2026-09-02 — Phase 5 (ROADMAP.md)
- Fresh repo-wide grep for `print(` turned up 20 calls never in the original scope — `capture/scrcpy_socket.py` (18) and `capture/adb_screencap.py` (2) — plus one in `main.py`'s config-load-failure path. Folded all of them into this phase: same reasoning as everything else this audit has flagged, a capture-backend failure overnight was going to a print() nobody would see.
- Routing `config/settings.py` through `app_logger` created a circular import (`app_logger.py` already imports `LoggingConfig`/`DebugConfig` from `config.settings`). Fixed by moving those two imports behind `TYPE_CHECKING` in `app_logger.py` — see key decisions.
- Free functions/classes with no natural `log_fn` (the three `config/*.py` loaders, both capture backends) call `app_logger.log()` directly rather than being threaded a `log_fn` parameter.
- `ui/app.py`'s resize-debug print deleted outright — scaffolding, per the option this item already offered.
- Verified with a full-repo compile pass and a functional test covering both import directions (starting fresh from `config.settings`, the harder circularity case) and confirming the missing-`settings.json` WARNING path fires correctly through the print fallback — first test attempt had a scoping bug (patched `config.paths.settings_path` instead of the name bound inside `config.settings`'s own namespace via `from ... import`), caught and fixed before trusting the result.
- Modified: bot/app_logger.py, config/settings.py, config/devices.py, config/profiles.py, capture/scrcpy_socket.py, capture/adb_screencap.py, main.py, ui/app.py, AUDIT.md, ROADMAP.md, CLAUDE.md.

### 2026-09-02 — Phase 6 (ROADMAP.md)
- Traced every actual read of `profile.behaviors` before touching anything — found the audit's list undersold the problem: `auto_farm_reset`/`end_run_reset` were stale duplicates of `TimerConfig` (already dead), and `rejoin_on_kick`/`rejoin_source`/`auto_rejoin`/`cascade_reset_on_lead_reset`/`move_to_private_on_revive_exhausted` were never read anywhere, in any profile. Only `cascade_reset_on_end_run`, `eaten_by_detection`, and `dead_state` were real.
- Landed the two real cascade fields on `TimerConfig` (`cascade_reset_enabled`, `cascade_reset_delay_after_lead_s`); a new `DeathBehaviorConfig` on `DeviceConfig` for the other five (`disable_auto_on_death`, `save_screenshot_on_death`, `revive_enabled`, `eaten_by_detection_enabled`, `eaten_by_detection_trigger_support_end_run`).
- `load_devices()` computes profile-aware migration defaults for entries missing these new fields (e.g. `eaten_by_detection_enabled` → `is_lead`) — no edits to the real `devices.json`. Verified against all 6 real configured devices: every migrated default exactly matches what that device's old profile assignment used to produce.
- `device_worker.py`'s three read sites (`_execute_end_run`, `_handle_dead_private`, `_handle_dead_public`) switched from `self.profile.behaviors.get(...)` to `self.cfg.timers.*`/`self.cfg.death_behavior.*`.
- Removed the now-empty `behaviors:` block from all four profile YAMLs and `ProfileConfig.behaviors` from the dataclass/loader — profiles are purely rule-set metadata now.
- Found and fixed a bug before it could bite the new fields: `ui/device_settings_dialog.py` had the identical "resets unexposed fields on every save" issue as `ui/settings_dialog.py` (Phase 4). Fixed with the same `dataclasses.replace()` pattern. New fields are not exposed as checkboxes in either dialog — that's Phase 11's job.
- Verified with a full-repo compile pass, per-device migration-default assertions against real `devices.json`, a `DeviceWorker` end-to-end test of the cascade-reset broadcast, a `save_devices`/`load_devices` round-trip, and a real-Tkinter `DeviceSettingsDialog` test confirming the new fields survive a save untouched.
- Modified: config/devices.py, config/profiles.py, config/constants.py, bot/device_worker.py, ui/device_settings_dialog.py, config/profiles/lead_private.yaml, config/profiles/support_private.yaml, config/profiles/lead_public.yaml, config/profiles/support_public.yaml, README.md, AUDIT.md, ROADMAP.md, CLAUDE.md.

---

## Standing instructions

These apply every session without being included in the prompt:

1. Read this file fully before touching any code.
2. Read app-framework.md from https://github.com/Rekot24/dev-standards before any architectural work.
3. Before building anything, explain what you are going to do and why. Wait for confirmation before proceeding.
4. Flag anything that conflicts with dev-standards before proceeding — do not comply silently.
5. No magic numbers or magic strings — all named values go in `config/constants.py` with a comment explaining what they mean and where they came from, **except UI layout constants** (pixel sizes, row heights, widget counts, and the like), which live as named module-level constants at the top of the UI file that uses them, not in `config/constants.py` — they have no config/settings meaning, they're facts about one screen's rendering. Every constant's comment (in either location) also carries a `[TUNABLE]` or `[INTERNAL]` tag:
   - `[TUNABLE]` — a user-adjustable value that will be exposed in the settings UI and overridable through the settings store. The constant is the default.
   - `[INTERNAL]` — an implementation fact. It needs a name but has no meaningful user context, and never surfaces in the UI.
   ```python
   # [TUNABLE] ADB command timeout — increase for slow or high-latency devices
   ADB_TIMEOUT_S = 10.0

   # [INTERNAL] Max 32-bit integer — used as "never timeout" for screen_off_timeout ADB command
   MAX_INT32 = 2147483647
   ```
   This makes ROADMAP Phase 12 (surfacing tunables in the global Settings dialog — distinct from Phase 11's per-device feature-flag checkboxes) mechanical: surface every `[TUNABLE]` constant, skip every `[INTERNAL]` one.
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
