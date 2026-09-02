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

## Phase 4 — Debug layer (Layer 3)

**Depends on:** Phase 1 (needs somewhere to route debug output) and Phase 2 (adding the new config fields cleanly).

- Add the master `debug.enabled` switch and per-category flags (`log_detections`, `log_actions`, `log_health`, `log_config_reads`, `screenshot_on_event`) to `DebugConfig`.
- Add the central `_debug(category, msg)` function described in the standard, checking both the master switch and the category flag before calling into the Phase 1 logger.
- Wire the UI debug section to show the master toggle collapsed by default with per-category checkboxes underneath, per the standard's UI convention.

---

## Phase 5 — Remove stray `print()` calls

**Depends on:** Phases 1 and 4 (there needs to be a real destination for these before deleting the `print()`s).

- [config/settings.py:82](config/settings.py#L82), [config/devices.py:88](config/devices.py#L88), [config/profiles.py:72](config/profiles.py#L72) (relocated from `bot/config_manager.py` by Phase 2, unchanged otherwise) — these are free functions with no logger access today; give them a lightweight module-level logger or accept a `log_fn` parameter.
- [ui/app.py:178](ui/app.py#L178) — the leftover resize-debug print becomes a `self._debug("ui", ...)` call or is deleted if it was scaffolding.

---

## Phase 6 — Promote behavior flags out of static YAML

**Depends on:** Phase 2 (needs the config split done to add fields without further bloating one file). Related to Phase 3 — same shape of change (giving a bare value a proper home in the settings store) applied to booleans instead of numbers.

Move `revive_enabled`, `disable_auto_on_death`, `save_screenshot`, `cascade_reset_on_end_run.enabled`, and `eaten_by_detection.enabled` out of `config/profiles/*.yaml` `behaviors` blocks and into `DeviceConfig` (or `Settings`, for the ones that aren't genuinely per-device). Reserve the YAML profiles for what they're actually good at — state-detection rule sets (`STATE_RULES`) — and make every one of these read live from the settings store each cycle, matching the Layer 1 rule ("checks its own enabled flag on every run, not once at startup") that the timer flags already follow correctly.

---

## Phase 7 — Dev vs. production error-handling mode

**Depends on:** Phases 1 and 4 (the switch needs a logging layer and follows the same settings-driven-toggle pattern the debug layer just established).

- Add the mode switch (dev = fail loudly / raise; prod = fail gracefully / log + fallback) to `Settings`.
- Update `DeviceWorker._run()`'s top-level catch ([bot/device_worker.py:161-164](bot/device_worker.py#L161-L164)) to branch on it — currently it always swallows and logs, even truly unexpected exceptions, which is fine for unattended production runs but makes bugs invisible while developing.

---

## Phase 8 — Feature-flag profile snapshot/restore

**Depends on:** Phase 6. Snapshotting only makes sense once the flags it would snapshot are actually centralized and live in the settings/device store — building this against the current static-YAML setup would mean redoing it once Phase 6 lands.

Add the standard's actual "Profile" concept: save the current set of feature-flag states under a name, restore it later. This is additive, not a replacement for the existing `lead_private`/`support_private`/etc. YAML profiles, which are a different (and valid) concept — state-detection rule sets — that just happen to share the word "profile."

---

## Phase 9 — Health-check visibility (opportunistic, low priority)

**Depends on:** Phase 1 (needs the logger) and Phase 3 (the timeout/threshold values being logged should already be named by this point). Once real log levels exist, add timing/log lines around the three blocking `adb` subprocess calls in `HealthMonitor.check()` ([bot/health_monitor.py:76-79](bot/health_monitor.py#L76-L79)) so a slow or hung health check shows up in the log instead of just silently extending the scan interval.

---

## Phase 10 — Tests (future layer, not yet required by the standard)

The standard itself defers this. Worth noting it becomes meaningfully cheaper *after* Phase 2 — `state_machine.resolve_state()`, `detector.find_in_frame()`, and the split config loaders are all pure-ish functions once separated out, and are the natural first candidates whenever testing does get picked up.

---

## Phase 11 — Per-device feature flag UI

**Depends on:** Phase 6 (flags must be live in settings store) 
and Phase 8 (profiles must exist to save/load from UI).

- Add checkbox panel to each device in the UI
- Groups: Detectors / Actions / Health responses / Timers
- Each checkbox reads from and writes to settings store live — no restart
- Health stats always visible regardless of checkbox state
- [Save as Profile...] and [Load Profile...] buttons per device
- Changing a checkbox takes effect on the next worker loop cycle

---

## Phase 12 — Surface `[TUNABLE]` constants in the Settings dialog

**Depends on:** Phase 3. This is a distinct UI surface from Phase 11 — Phase 11 is per-device boolean feature flags (detectors/actions/health responses, one checkbox panel per device); this phase is global numeric/threshold values (timeouts, retry delays, the thermal-throttle multiplier, etc.) in the one global Settings dialog, the same place `HealthConfig`/`DebugConfig`/`LoggingConfig` fields already live. The two don't block each other and can happen in either order.

- For every constant in `config/constants.py` tagged `[TUNABLE]` (standing instruction 5 in CLAUDE.md — every constant is tagged `[TUNABLE]` or `[INTERNAL]` when it's created in Phase 3), add a field to the relevant config dataclass (`Settings` or one of its nested configs, following the pattern `LoggingConfig` already established) and a corresponding row in `ui/settings_dialog.py`.
- Skip every `[INTERNAL]` constant entirely — by definition, it has no meaningful user context and should never surface in the UI.
- Mechanical once Phase 3's tagging exists: the tag on each constant is the checklist for this phase, not a judgment call made fresh here.

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
