# Roadmap — Closing the Standards Gap

Suggested build order for the items in [`AUDIT.md`](AUDIT.md), sequenced by dependency: each phase either unblocks the next or is safe to do in parallel with no risk of rework. Strengths already in place (data models, docstrings, defensive checks, folder layout, etc.) aren't listed here — this is just the missing/needs-refactor items, in the order to tackle them.

---

## Phase 0 — Quick wins (no dependencies, do anytime)

These don't block or get blocked by anything else. Good warm-up work, or fill-in between the phases below.

1. [x] **Write `README.md`.** Done — describes the app and what each folder is responsible for.
2. [x] **Fix UI → worker direct calls.** Done — added `DeviceManager.is_device_running(serial)` and `DeviceManager.trigger_end_run(serial)` (backed by a new `DeviceWorker.request_manual_end_run()`), and pointed the UI at those instead of `manager._workers`/`worker._execute_end_run()`. Turned up a real bug in passing: the old direct call passed no `results` argument to a method that required one, so the manual "End Run" button was throwing on every click — fixed as part of the same change.
3. [ ] **Adopt `type: what/why` commit messages** going forward. Process change only — no code dependency, starts paying off on the very next commit.

---

## Phase 1 — Logging layer (Layer 7) ✅ Done

**Why first (of the substantive work):** almost every other gap either produces log output or needs to route existing `print()`/ad hoc `self._log()` calls somewhere real. Building the debug layer, cleaning up stray `print()`s, and adding a dev/prod error mode all assume a logging layer already exists — building them before this would mean redoing the plumbing twice.

- [x] Add `logs/app.log` (rotating), `logs/errors.log` (errors and criticals only, always on).
- [x] Give the existing `_log()` calls real levels (DEBUG/INFO/WARNING/ERROR/CRITICAL) instead of one undifferentiated stream.
- [x] Route through one unified function per the standard's pattern — file + UI queue + console from a single call site — rather than three separate write paths.
- [x] Add the `logging` block to `Settings` (`enabled`, `level`, `log_to_file`, `log_to_console`, `max_file_size_mb`, `backup_count`), plus a UI section in the Settings dialog to edit it live.

Landed as [bot/app_logger.py](bot/app_logger.py) (new module, wraps stdlib `logging` with `RotatingFileHandler`) + `LoggingConfig` in what was then `bot/config_manager.py` (now `config/settings.py`, since Phase 2). `App.log()` is the fork point — one call writes to `app_logger` and queues the UI display. Every `self._log(...)` call site in `device_worker.py` and `device_manager.py` was reclassified with a real level, not just given a default. `DeviceManager.reload_settings()` calls `app_logger.configure()` again so a level/console/file toggle in the Settings dialog takes effect immediately, no restart — same live-reload pattern as `HealthConfig`/`DebugConfig`.

This was the single highest-value item in the audit — it's also the one the standard's own motivating scenario ("something goes wrong at 3am while the farm runs unattended") points straight at, and it's the one thing that was missing that this app's actual use case (unattended overnight runs) most needed.

---

## Phase 2 — Split `config_manager.py` ✅ Done

**Why here:** Phases 3 and 6 both need to add new fields to config (magic-number promotions, promoted feature flags). Doing that inside a 392-line file that already owns settings + devices + profiles + validation makes those changes riskier and harder to review. Splitting first means every later phase adds fields to a small, single-purpose file instead of a monolith.

- [x] `config/settings.py` — `Settings`, `HealthConfig`, `DebugConfig`, `LoggingConfig`, load/save/validate.
- [x] `config/devices.py` — `DeviceConfig`, `TimerConfig`, `DetectorConfig`, load/save/validate.
- [x] `config/profiles.py` — `ProfileConfig`, load/load_all (still load-only — profiles are edited by hand, not through the UI).
- [x] Keep the public function names stable (`load_settings`, `load_devices`, etc.) so `main.py` and the UI dialogs don't need to change beyond their imports.

Landed with one addition beyond the original plan: a `config/paths.py` holding the five path-resolution helpers all three files shared, rather than each getting its own copy (three copies of `_project_root()` etc. would have been the same duplication problem in a new shape). `bot/config_manager.py` deleted outright — no compatibility shim, no other consumers of it existed. All 10 files that imported from it were repointed to the right new module(s); verified with both a full-repo compile check and an import-chain + functional round-trip smoke test (`load_settings`/`load_devices`/`load_profile` against the real config files, including the 6 real configured devices).

---

## Phase 3 — No magic numbers ✅ Done

**Depends on:** Phase 2. Most of what needs naming here isn't just a code constant — it's the same *kind* of value `HealthConfig` already extracted correctly for battery/temp thresholds (operational tuning knobs: timeouts, settle delays, retry counts). Doing this once the config split exists means these land as new fields on the right small file instead of more clutter on a monolith, and it means Phase 4's debug layer and Phase 9's health-check logging report on values that already have names instead of raw numbers.

- [x] **Consolidate the duplicated ADB timeout.** Landed as three tiers, not one collapsed value — `ADB_QUICK_TIMEOUT_S`/`ADB_DEFAULT_TIMEOUT_S`/`ADB_LAUNCH_TIMEOUT_S` (plus `ADB_SCREENCAP_TIMEOUT_S`, `ADB_SCREENCAP_BATCH_TIMEOUT_S`, `ADB_RECONNECT_SETTLE_S`) in `config/constants.py`, live-wired via a new `AdbConfig` on `Settings` wherever a call site already holds a live settings reference; used as named static defaults (not settings-store-threaded) in `bot/actions.py` and the three standalone tool dialogs — see AUDIT.md §4 for why that boundary was drawn there.
- [x] **Name the device-recovery/settle delays in `device_worker.py`.** Landed on `HealthConfig` as planned: `crash_detect_after_s`, `crash_recovery_settle_s`, `battery_sleep_settle_s`, `battery_sleep_poll_s`, `wake_settle_s`, `temp_pause_poll_s` — read live from `self.settings.health.*` at each use site.
- [x] **Name `_max_unknown_s`, the thermal-throttle `2.0` multiplier, and the `0.05` sleep floor.** `_max_unknown_s` removed entirely (replaced by the live `crash_detect_after_s` read above); `thermal_throttle_multiplier` is a live `HealthConfig` field; the sleep floor is `LOOP_SLEEP_FLOOR_S`, `[INTERNAL]` in `config/constants.py`.
- [x] **Dedupe the `0.82` template-confidence default.** All five call sites (four in `detector.py` + `Settings.template_confidence_default`) now reference one `DEFAULT_TEMPLATE_CONFIDENCE` constant — verified via `inspect.signature` in the phase's smoke test that they're the same object, not just the same value.
- [x] **Name the UI resize math.** Landed as module-level constants in `ui/app.py` itself, not `config/constants.py` — a scope refinement made mid-phase (see CLAUDE.md instruction 5): UI layout facts stay next to the UI code that uses them.
- [x] **Name the health-monitor temperature-parsing heuristics.** `THERMAL_MILLIDEGREE_CUTOFF`, `MIN_PLAUSIBLE_TEMP_C`, `MAX_PLAUSIBLE_TEMP_C` — all `[INTERNAL]`.

Also picked up along the way (found during implementation, not in the original audit list): the four unnamed `* 60` minute→second conversions (`SECONDS_PER_MINUTE`), and four more unnamed literals in `capture/scrcpy_socket.py` beyond the two retry sleeps the audit specifically called out (`SCRCPY_PORT_RANGE_SIZE`, decode-thread join timeout, teardown-command timeout, socket-connect-attempt timeout).

Every constant added is tagged `[TUNABLE]` or `[INTERNAL]` per CLAUDE.md's refined instruction 5 — this is what makes Phase 12 mechanical rather than a fresh judgment call.

This phase touched nearly every file, as expected — confirmed with a full-repo compile pass plus a functional smoke test (construction + settings round-trip + `DeviceWorker` wiring, including confirming `HealthMonitor.adb_cfg` is the live `Settings.adb` object, not a disconnected default).

---

## Phase 4 — Debug layer (Layer 3) ✅ Done

**Depends on:** Phase 1 (needs somewhere to route debug output) and Phase 2 (adding the new config fields cleanly).

- [x] Add the master `debug.enabled` switch and per-category flags (`log_detections`, `log_actions`, `log_health`, `log_config_reads`, `screenshot_on_event`) to `DebugConfig`.
- [x] Add the central `_debug(category, msg)` function described in the standard, checking both the master switch and the category flag before calling into the Phase 1 logger.
- [x] Wire the UI debug section with checkboxes for every category.

Landed as `app_logger.debug(cfg, category, msg, log_fn)` in `bot/app_logger.py`, with a thin `_debug(category, msg)` wrapper on `DeviceWorker` and `DeviceManager` delegating to it through their existing `_log()` — so debug output reaches the same file/console/UI destinations as everything else. Resolved a real tension in the standard before implementing: Layer 7 lists "state changed" as an always-on INFO example, while Layer 3 lists `log_state_changes` as a debug category with its own toggle. Decision (confirmed with the user): additive, not overlapping — every Phase 1 INFO/WARNING/ERROR log stays exactly as-is, always on; the new debug categories add supplementary, opt-in detail on top (detector scores every scan for `log_detections`, raw health values every scan for `log_health`, the results dict at a transition for `log_state_changes`, dispatch tracing for `log_actions`, reload tracing for `log_config_reads`). Turning debug off never makes an existing log line disappear.

Skipped the standard's "collapsed by default" UI treatment — flat grouped checkboxes in the existing Debug section, matching the dialog's current style, rather than adding new expand/collapse widget behavior for a cosmetic nicety.

Bonus fix, found while wiring the new checkboxes: `SettingsDialog._save()` was constructing fresh `HealthConfig`/`DebugConfig`/`LoggingConfig` objects from only its exposed fields, silently resetting every Phase 3 field the dialog doesn't have a row for (all of `AdbConfig`, `HealthConfig`'s settle/poll delays) to its default on every save. Fixed with `dataclasses.replace()` off the originally-loaded `Settings` — see AUDIT.md §2.

---

## Phase 5 — Remove stray `print()` calls ✅ Done

**Depends on:** Phases 1 and 4 (there needs to be a real destination for these before deleting the `print()`s).

- [x] `config/settings.py`, `config/devices.py`, `config/profiles.py` (relocated from `bot/config_manager.py` by Phase 2) — call `app_logger.log()` directly; they're free functions with no natural instance to route through.
- [x] `ui/app.py`'s resize-debug print — deleted outright (scaffolding, per the option this item already offered), rather than given a new debug category for one low-value line.
- [x] **Scope grew on a fresh grep:** 20 more `print()` calls in `capture/scrcpy_socket.py` (18) and `capture/adb_screencap.py` (2) that were never in this item's original list, plus one in `main.py`'s config-load-failure path — same fix, same reasoning (a capture-backend failure overnight was going to a print() nobody would see). These reach the file/console logger, not the UI panel — threading a `log_fn` through `make_backend()` for that is out of this phase's scope, same kind of boundary as Phase 3's `bot/actions.py` call; `DeviceWorker` already surfaces the user-facing symptom (frame capture returning `None`) to the UI regardless.
- [x] **Unplanned prerequisite:** routing `config/settings.py` through `app_logger` created a circular import (`app_logger.py` already imports `LoggingConfig`/`DebugConfig` from `config.settings`). Fixed by moving those two imports behind `TYPE_CHECKING` in `app_logger.py` — they're never constructed or isinstance-checked there, only attribute-read, so this costs nothing at runtime.

Verified with a full-repo compile pass and a functional test confirming both import directions (starting from `config.settings` fresh, the harder circularity case) and that the missing-`settings.json` WARNING path actually fires through the print fallback.

---

## Phase 6 — Promote behavior flags out of static YAML ✅ Done

**Depends on:** Phase 2 (needs the config split done to add fields without further bloating one file). Related to Phase 3 — same shape of change (giving a bare value a proper home in the settings store) applied to booleans instead of numbers.

- [x] Move `revive_enabled`, `disable_auto_on_death`, `save_screenshot`, `cascade_reset_on_end_run.enabled`, and `eaten_by_detection.enabled` out of `config/profiles/*.yaml` `behaviors` blocks and into `DeviceConfig`.
- [x] Reserve the YAML profiles for what they're actually good at — state-detection rule sets.
- [x] Make every one of these read live from the settings store each cycle.

Before touching anything, traced every actual read of `profile.behaviors` and found the audit's list undersold the problem: most of the `behaviors:` block was already dead code (`auto_farm_reset`/`end_run_reset` stale duplicates of `TimerConfig`, and `rejoin_on_kick`/`rejoin_source`/`auto_rejoin`/`cascade_reset_on_lead_reset`/`move_to_private_on_revive_exhausted` never read anywhere, in any profile). Only three blocks were real: `cascade_reset_on_end_run`, `eaten_by_detection`, `dead_state`.

Landed as two new fields on `TimerConfig` (`cascade_reset_enabled`, `cascade_reset_delay_after_lead_s` — the "reset cycle" theme fits better than a standalone class, and the reading code already lives in `device_worker.py`'s Timer logic section) and a new `DeathBehaviorConfig` on `DeviceConfig` for the other five. `load_devices()` computes profile-aware migration defaults (e.g. `eaten_by_detection_enabled` → `is_lead`) so existing `devices.json` entries keep behaving identically with zero file edits — verified against all 6 real configured devices. The `behaviors:` block is now empty in every profile YAML, so it's removed from all four files and from `ProfileConfig` itself; profiles are purely rule-set metadata now.

Found and fixed in passing: `ui/device_settings_dialog.py` had the same "resets unexposed fields to their dataclass default on every save" bug as `ui/settings_dialog.py` (Phase 4) — fixed with the same `dataclasses.replace()` pattern. New fields are *not* exposed as checkboxes in either dialog — that's explicitly Phase 11's job, which already lists this phase as its prerequisite.

Verified with a full-repo compile pass, assertions that every real device's migration-computed defaults exactly match its old profile-derived behavior, a `DeviceWorker` end-to-end test of the cascade-reset broadcast reading the new field, a `save_devices`/`load_devices` round-trip, and a real-Tkinter `DeviceSettingsDialog` test confirming the new fields survive a save untouched.

---

## Phase 7 — Dev vs. production error-handling mode ✅ Done

**Depends on:** Phases 1 and 4 (the switch needs a logging layer and follows the same settings-driven-toggle pattern the debug layer just established).

- [x] Add the mode switch (dev = fail loudly / raise; prod = fail gracefully / log + fallback) to `Settings` — `development_mode: bool`, default `False`.
- [x] Update `DeviceWorker._run()`'s top-level catch to branch on it — always logs (unchanged), re-raises only in development mode.

Scope discipline decided up front and stuck to: this does *not* retrofit every `except Exception` in the codebase. Layer 6's own example distinguishes named/expected failures (always handled gracefully, every mode) from the genuinely-unexpected bucket at the outermost boundary (mode-dependent) — most of the broad catches elsewhere (`bot/actions.py`, the capture backends' inner methods, `detection/detector.py`) are the first kind and were correctly left untouched.

One analogous site found and included by design, not accident: `capture/scrcpy_socket.py`'s `_decode_loop()` runs its own background thread with its own outermost catch-all (previously: log and `break`, silently ending that device's frame decoding on any unexpected error) — same category as `DeviceWorker._run()`'s loop, so it got the same treatment. Required threading `development_mode` through `make_backend()` into both `ScrcpySocketBackend` and `ADBScreencapBackend` (the latter accepts-but-doesn't-use it, for interface parity — it has no background thread of its own to crash loudly in).

UI: one checkbox added to the Settings dialog's General section, though ROADMAP didn't explicitly ask for it — unlike Phase 3/6's tunables, nothing later promises a dedicated UI phase for this one flag, so leaving it hand-edit-only in `settings.json` would have been permanent, not deferred.

Verified by actually triggering exceptions at runtime, not just asserting config values: a background-thread test forcing `DeviceWorker._loop_iteration()` to raise repeatedly confirmed production mode logs every error and keeps the worker thread alive (5 iterations survived), while development mode logs once and lets the thread die with a full traceback (visible in the test output) after exactly 1 call. Same live test against `_decode_loop()` confirmed the same two behaviors there.

---

## Phase 8 — Feature-flag profile snapshot/restore ✅ Done

**Depends on:** Phase 6. Snapshotting only makes sense once the flags it would snapshot are actually centralized and live in the settings/device store — building this against the current static-YAML setup would mean redoing it once Phase 6 lands.

Add the standard's actual "Profile" concept: save the current set of feature-flag states under a name, restore it later. This is additive, not a replacement for the existing `lead_private`/`support_private`/etc. YAML profiles, which are a different (and valid) concept — state-detection rule sets — that just happen to share the word "profile."

Landed as `BehaviorPreset` in [config/presets.py](config/presets.py) — deliberately not called "profile" in code, to avoid exactly the collision this item's own description warns about (`config/profiles.py` already owns that word for rule sets). Snapshots `TimerConfig` + `DeathBehaviorConfig` only; `save_preset`/`load_preset`/`load_all_presets`/`delete_preset`/`list_preset_names`/`apply_preset`, all `dataclasses.replace()`-based. No presets shipped by default — this is the data layer Phase 11's Save-as/Load buttons call into, not the UI itself.

**Scope addition mid-phase, at the user's request:** `DeviceConfig.is_lead: bool` renamed to `role: str` (`ROLE_LEAD`/`ROLE_SUPPORT` in `config/constants.py`) throughout the codebase — every read site in `bot/device_worker.py`, `bot/device_manager.py`, both UI dialogs, `ui/device_panel.py`, plus validation and the migration path in `load_devices()` for entries with a legacy `is_lead` boolean. Before making the change, traced every actual read of `is_lead`/`role`/`server_type` in the codebase to confirm excluding `role` from `BehaviorPreset` couldn't strip any role-gated bot-loop logic — it can't, since every such decision lives in the code that reads `DeviceConfig.role`, never in the snapshotted fields. Also removed `ProfileConfig.role` (a same-named, confirmed-dead field that would have been a landmine sitting next to the new authoritative one) and the corresponding `role:` line from all four profile YAML files.

**Phase 11 requirement captured for later, not built now:** when role is lead, lead-only behavior options (`eaten_by_detection_*`, `cascade_reset_*`) should become visible/active in the per-device checkbox UI; when support, they hide. Role itself stays out of `BehaviorPreset` — it's device identity, not a behavior to snapshot. See CLAUDE.md.

**Incident during this phase, not caused by the rename:** while testing, found that `config/devices.json` and `config/settings.json` — the real, gitignored files — had been silently overwritten by earlier phases' test scripts (Phase 6 for devices.json; Phase 3 and Phase 7 for settings.json). Root cause: those tests patched `config.paths.X_path` to isolate themselves, but `config/devices.py`/`config/settings.py` each do `from config.paths import X_path`, binding their own copy of the name at import time — patching the origin module doesn't touch that bound copy, so the "isolated" test's `save_*()` call silently hit the real file. Full writeup, recovery actions taken, and the testing-methodology fix are in CLAUDE.md's session log and key decisions — including two new committed recovery aids (`config/settings.example.json`, `config/devices.example.json`) added directly because of this.

---

## Phase 9 — Health-check visibility (opportunistic, low priority) ✅ Done

**Depends on:** Phase 1 (needs the logger) and Phase 3 (the timeout/threshold values being logged should already be named by this point). Once real log levels exist, add timing/log lines around the three blocking `adb` subprocess calls in `HealthMonitor.check()` so a slow or hung health check shows up in the log instead of just silently extending the scan interval.

Landed as per-sub-check timing (battery, temperature, ADB connectivity individually, not an aggregate — pinpoints which call is slow) logged as `WARNING` via `app_logger.log()` — same pattern Phase 5 established for classes without a natural `log_fn`. New `HealthConfig.health_check_slow_threshold_s` (default `2.0s`, `[TUNABLE]`, `HEALTH_CHECK_SLOW_THRESHOLD_S` in `config/constants.py`) — live from day one since `HealthMonitor` already holds a `HealthConfig` reference, unlike `bot/actions.py`'s scope-boundary cases in Phase 3. Deliberately unconditional (not gated behind Phase 4's debug system) — a slow/hung health check is Layer 7's own definition of `WARNING` ("something unexpected but recoverable"), not opt-in diagnostic detail; Phase 4's `log_health` debug category already covers the opt-in *values*, this is unconditional *timing*, a different concern. No Settings-dialog row — same Phase 12 deferral as Phase 3's other `HealthConfig` additions.

Verified with a functional test that actually calls the logging logic with forced elapsed times (not just asserting the threshold value round-trips) — confirmed both a slow case fires the right message with the right check name and timing, and a fast case stays silent — plus a live `check()` call and a settings round-trip.

---

## Phase 10 — Tests (future layer, not yet required by the standard)

The standard itself defers this. Worth noting it becomes meaningfully cheaper *after* Phase 2 — `state_machine.resolve_state()`, `detector.find_in_frame()`, and the split config loaders are all pure-ish functions once separated out, and are the natural first candidates whenever testing does get picked up.

---

## Phase 11 — Per-device feature flag UI ✅ Done

**Depends on:** Phase 6 (flags must be live in settings store) 
and Phase 8 (profiles must exist to save/load from UI).

- [x] Add checkbox panel to each device in the UI (within device settings screen)
- [x] Groups: Detectors / Actions / Health responses / Timers
- [x] Each checkbox reads from and writes to settings store live — no restart
- [x] Health stats always visible regardless of checkbox state
- [x] Save as Preset... / Load Preset... buttons per device
- [x] Changing a checkbox takes effect on the next worker loop cycle

**Before building UI, traced what each of the four named groups would actually be backed by** — two (Timers, Actions) already existed as live `DeviceConfig` fields from Phase 6/8; two (Detectors, Health responses) didn't exist as toggleable flags at all. Detectors group had no per-device disable mechanism (only the profile's `detectors_required` list, shared across every device on that profile); Health responses turned out to have no enabled flag *at all* — battery-sleep/temp-pause fired unconditionally whenever a threshold was crossed, a real instruction-9 violation that only surfaced from tracing this. Confirmed with the user: add both missing pieces of data model, not just scope down to what already existed. See AUDIT.md for the two new findings this produced.

**New data model:** `DeviceConfig.disabled_detectors: List[str]` (filtered out of `self.profile.detectors_required` each cycle) and a new `HealthResponseConfig` (`battery_protection_enabled`, `temp_protection_enabled`, both default `True` — preserves current always-on behavior for every existing device) on `DeviceConfig.health_response`, gating `_enter_battery_sleep()`/`_enter_temp_pause()`. `BehaviorPreset` (Phase 8) expanded to cover both new fields alongside the original `timers`/`death_behavior` — a preset covering only half a device's behavior would be a confusing half-measure now that there's more of it.

**UI restructured into a `ttk.Notebook`** (General / Timers / Actions / Health / Detectors tabs) rather than more rows on an already-full flat dialog — the same pattern `tools/image_capture_tool.py` already uses for the identical problem. Actions tab's eaten-by rows show/hide live via a Tkinter variable trace on the role checkbox (the requirement captured in CLAUDE.md ahead of this phase); Detectors tab's checklist rebuilds live via a trace on the Profile combo, since required-detector lists differ by profile (public adds `revive_button`). Save as Preset.../Load Preset... live in the persistent bottom button row, not a tab, so they're reachable regardless of which tab is open — both operate on the dialog's in-memory state via a shared `_build_result()`/`_apply_to_widgets()` pair, no need to Save/Cancel first. No delete-preset UI — the data layer supports it, this item only asked for save/load.

Verified with a real-Tkinter test exercising the actual reactivity, not just widget construction: flipped the role checkbox and confirmed the eaten-by rows' pack state changed (caught a test-methodology issue along the way — `winfo_ismapped()` reflects Notebook tab-selection, not pack/pack_forget state; `winfo_manager()` is the correct, tab-independent check), changed the Profile combo and confirmed the detector checklist rebuilt with the right count, and ran a full save-as-preset → modify → load-preset cycle confirming the original values came back through the dialog's own widgets.

---

## Phase 12 — Surface `[TUNABLE]` constants in the Settings dialog ✅ Done

**Depends on:** Phase 3. This is a distinct UI surface from Phase 11 — Phase 11 is per-device boolean feature flags (detectors/actions/health responses, one checkbox panel per device); this phase is global numeric/threshold values (timeouts, retry delays, the thermal-throttle multiplier, etc.) in the one global Settings dialog, the same place `HealthConfig`/`DebugConfig`/`LoggingConfig` fields already live. The two don't block each other and can happen in either order.

- [x] For every constant in `config/constants.py` tagged `[TUNABLE]`, add a field to the relevant config dataclass and a corresponding row in `ui/settings_dialog.py`.
- [x] Skip every `[INTERNAL]` constant entirely.
- [x] Mechanical once Phase 3's tagging exists — confirmed true.

**Housekeeping fix first:** `SCRCPY_SERVER_BIND_SETTLE_S`'s comment was tagged `[TUNABLE]` but its own prose said *"Left `[INTERNAL]` rather than wired to a live settings field this phase"* — a leftover Phase 3 contradiction that would have wrongly pulled it into this phase's checklist. Corrected the tag to `[INTERNAL]`, matching its documented intent, before doing the pass.

**Scope finding:** every remaining `[TUNABLE]` constant already had a live backing field on `HealthConfig`/`AdbConfig` from Phases 3/6/9 — `config/settings.py`'s dataclasses, `load_settings()`, and `save_settings()` needed zero changes. This phase was purely `ui/settings_dialog.py` work: 14 new rows (6 `AdbConfig` timeout fields, 8 `HealthConfig` recovery/timing fields) that had constants and live settings-store plumbing since Phase 3/9 but no UI row until now. One exclusion: `CASCADE_RESET_DELAY_S` backs `TimerConfig.cascade_reset_delay_after_lead_s`, a per-device field already exposed in Phase 11's device dialog (Timers tab) — it doesn't belong in the global Settings dialog.

**Layout:** `SettingsDialog` restructured into a `ttk.Notebook` (General / ADB Timeouts / Health / Debug / Logging) rather than 14 more rows bolted onto the flat ~29-row layout — same pattern Phase 11 used for `ui/device_settings_dialog.py`'s identical "too much content" problem, at the user's explicit direction. The 6 new ADB rows form their own tab (the dialog had no ADB section before this); the 8 new Health rows landed as a new "Device Recovery Timing" section on the existing Health tab, alongside the pre-existing Battery/Temperature threshold rows. `_save()` keeps the same `dataclasses.replace()`-off-`self._original` pattern (Phase 4/6's fix), extended to also replace `adb=` and the new `health=` fields — anything this dialog still doesn't expose keeps passing through unchanged.

Verified with a full-repo compile pass and a functional real-Tkinter test: constructed the dialog, confirmed the Notebook has exactly the 5 expected tabs in order, mutated a value on each new tab plus one on an existing tab, called `_save()`, and asserted both that the mutated values landed on `dlg.result` and that untouched fields (`adb.launch_timeout_s`, `health.battery_resume_percent`, all of `debug`/`logging`) passed through from the original `Settings` object unchanged.

---

### Dependency chain at a glance

```
Phase 0 (anytime) ────────────────────────────────────────────────────────

Phase 1 (logging) ──┬─→ Phase 4 (debug layer) ──┬─→ Phase 5 (remove prints)
                     │                            └─→ Phase 7 (dev/prod error mode)
                     └─→ Phase 9 (health-check visibility)

Phase 2 (config split) ──┬─→ Phase 3 (no magic numbers) ──┬─→ Phase 4
                          │                                ├─→ Phase 9
                          │                                └─→ Phase 12 (surface [TUNABLE] constants)
                          ├─→ Phase 6 (promote behavior flags) ──┬─→ Phase 8 (flag snapshots)
                          │                                       └─→ Phase 11 (per-device flag UI)
                          ├─→ Phase 7
                          └─→ Phase 10 (tests, whenever picked up)
```
