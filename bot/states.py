"""
bot/states.py

All game state name constants.

States represent what screen or condition the game is currently in.
The state machine resolves one of these per scan from detector results.
"""

# Active game states
STATE_IN_RUN        = "IN_RUN"        # Auto-farming in progress
STATE_DEAD          = "DEAD"          # Death screen visible
STATE_LOBBY         = "LOBBY"         # In game lobby, not in a tank
STATE_LOADING       = "LOADING"       # Loading screen between states
STATE_JOINING       = "JOINING"       # Currently joining a tank
STATE_DISCONNECTED  = "DISCONNECTED"  # Lost connection to tank / kicked

# System states (set by worker, not by state machine)
STATE_CRASHED       = "CRASHED"       # Roblox not running or not responding
STATE_UNKNOWN       = "UNKNOWN"       # No detector rules matched

# Health states (set by health monitor, not by state machine)
STATE_BATTERY_SLEEP = "BATTERY_SLEEP" # Device sleeping due to low battery
STATE_TEMP_PAUSE    = "TEMP_PAUSE"    # Device paused due to high temperature
STATE_ADB_LOST      = "ADB_LOST"      # ADB connection dropped

# All states that mean the bot loop is suspended
SUSPENDED_STATES = {STATE_BATTERY_SLEEP, STATE_TEMP_PAUSE, STATE_ADB_LOST, STATE_CRASHED}

# All states where the device is in-game (not in system/health states)
INGAME_STATES = {STATE_IN_RUN, STATE_DEAD, STATE_LOBBY, STATE_LOADING, STATE_JOINING, STATE_DISCONNECTED, STATE_UNKNOWN}
