#!/bin/sh
# Run on the board as root; visual confirmation is still required.
set -eu
backlight=/sys/class/backlight/ocp8178
previous=$(cat "$backlight/brightness")
[ "$(cat "$backlight/max_brightness")" -eq 31 ]
[ "$(cat "$backlight/bl_power")" -eq 0 ] || {
    echo 'Panel must be unblanked before the visual test.' >&2
    exit 1
}
[ "$previous" -gt 0 ] && [ "$previous" -le 31 ]
warning_script=$(dirname "$0")/speaker_audio.py
[ -f "$warning_script" ]
warning_owner=${NEO_WARNING_OWNER:-}
if [ -z "$warning_owner" ]; then
    warning_owner=$(/usr/bin/python3 -c 'import uuid; print(uuid.uuid4().hex)')
fi
[ -c /dev/tty1 ] && [ -w /dev/tty1 ] || {
    echo 'The local tty1 console is required for the visual test.' >&2
    exit 1
}
exec 3> /dev/tty1

announce() {
    printf '%s\n' "$1"
    printf '\r\n%s\r\n' "$1" >&3
}

restore() {
    result=$?
    trap - EXIT
    if ! printf '%s\n' "$previous" > "$backlight/brightness"; then
        result=1
    fi
    printf 'Restored brightness=%s; actual=' "$previous"
    actual=$(cat "$backlight/actual_brightness") || result=1
    printf '%s\n' "$actual"
    [ "$actual" = "$previous" ] || result=1
    if [ "$result" -eq 0 ]; then
        announce "Done. Restored level $previous/31." || result=1
    else
        announce 'Test failed; check the captured log.' || result=1
    fi
    announce 'Press Enter to redisplay login prompt.' || result=1
    exit "$result"
}
trap restore EXIT
trap 'exit 130' HUP INT TERM

step() {
    if [ "$1" -eq 0 ]; then
        /usr/bin/python3 -B "$warning_script" --warn-screen --owner "$warning_owner"
    fi
    printf '%s\n' "$1" > "$backlight/brightness"
    actual=$(cat "$backlight/actual_brightness")
    printf '%s requested=%s actual=%s\n' "$(date -u +%FT%TZ)" "$1" "$actual"
    [ "$actual" -eq "$1" ]
    announce "$3: $1/31 (readback $actual)"
    sleep "$2"
}

printf 'Starting brightness=%s; dim/medium/bright, then three off/on cycles.\n' "$previous"
announce 'GameShellNeo backlight test'
for remaining in 10 8 6 4 2; do
    announce "Starts in $remaining seconds..."
    sleep 2
done
step 1 4 '1/3 DIM'
step 16 4 '2/3 MEDIUM'
step 31 4 '3/3 BRIGHT'
for cycle in 1 2 3; do
    announce "Cycle $cycle/3: going dark for 2 seconds"
    sleep 2
    step 0 2 "Cycle $cycle OFF"
    step 31 2 "Cycle $cycle ON"
done
