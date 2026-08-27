# Android Platform Tools

Be Fish Farm Manager is designed to use a repository-local copy of ADB so the
application does not depend on a system-wide Android Platform Tools install or
machine-specific PATH settings.

Populate this folder by running from the repository root:

```bash
python tools/bootstrap_adb.py
```

The bootstrap script downloads the official Android Platform Tools archive from
Google for the current operating system and extracts it to:

`vendor/android/platform-tools/`

At runtime the application prefers this local copy. If it is absent, it falls
back to an `adb` executable already available on the system PATH.

The downloaded binaries are intentionally not committed to Git. They are
platform-specific and update independently from the application source. The
bootstrap script makes a fresh clone reproducible without requiring a manual
system installation.

The scrcpy capture backend does not require a separately installed `scrcpy`
executable. It uses the repository's `assets/scrcpy-server.jar` directly and
PyAV for decoding.
