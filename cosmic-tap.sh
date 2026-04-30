#!/bin/bash
#
# Launcher / App Library double-tap script for COSMIC desktop.
#
# Installation:
# - run install.sh, or copy this script to ~/bin/cosmic-tap
# - set the default action for the SUPER key to 'disabled'
# - add a custom keyboard shortcut SUPER -> /home/$USER/bin/cosmic-tap
#
# Afterwards a single tap on SUPER will bring up the COSMIC Launcher, while
# a double tap will bring up COSMIC Applications.
#
# How it works:
#
# Each tap on SUPER starts a new instance of this script. The first instance
# writes a state file and goes to sleep. If nothing happens in the next 300ms,
# it will wake up, check the state file, notice it's still there, delete it,
# then launch the Launcher.
#
# If another tap occurs during the 300ms, the second instance will notice a
# state file is already present. It will delete the file and immediately
# launch Applications.
#
# When the first instance wakes up, it will find the state file gone, and
# will exit without doing anything. 

# For testing only:
# notify-send "cosmic-tap.sh started" "The Super key was pressed"

STATE_FILE="/dev/shm/cosmic_super_tap" # Path to the in-memory state file
TIMEOUT=0.2 # Timeout in seconds, adjust as needed

SINGLE_TAP_ACTION="cosmic-launcher" # Command to launch on single tap
DOUBLE_TAP_ACTION="cosmic-app-library" # Command to launch on double tap

if [ -f "$STATE_FILE" ]; then
    # If the file exists, this is the second tap
    rm "$STATE_FILE"
    $DOUBLE_TAP_ACTION
else
    # First tap: Create the timer file and wait for the second tap or timeout
    touch "$STATE_FILE"
    sleep $TIMEOUT

    # If the file still exists after sleep, the second tap never happened
    if [ -f "$STATE_FILE" ]; then
        rm "$STATE_FILE"
        $SINGLE_TAP_ACTION
    fi
fi
