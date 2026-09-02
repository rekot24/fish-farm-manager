"""
config/

All configuration for the app lives here: the JSON/YAML data files
themselves, and the modules that load, validate, and save them.

  config/paths.py     — shared path resolution, used by all three below
  config/settings.py  — global app settings (config/settings.json)
  config/devices.py   — per-device configuration (config/devices.json)
  config/profiles.py  — behavior/logic profiles (config/profiles/*.yaml,
                         read-only at runtime)

Each is single-purpose and independently importable — split out of what
used to be one bot/config_manager.py file handling all three.
"""
