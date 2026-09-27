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
[ "$previous" -ge 0 ] && [ "$previous" -le 31 ]

restore() {
    result=$?
    trap - EXIT
    if ! printf '%s\n' "$previous" > "$backlight/brightness"; then
        result=1
    fi
    printf 'Restored brightness=%s; actual=' "$previous"
    cat "$backlight/actual_brightness"
    exit "$result"
}
trap restore EXIT
trap 'exit 130' HUP INT TERM

step() {
    printf '%s\n' "$1" > "$backlight/brightness"
    actual=$(cat "$backlight/actual_brightness")
    printf '%s requested=%s actual=%s\n' "$(date -u +%FT%TZ)" "$1" "$actual"
    [ "$actual" -eq "$1" ]
    sleep "$2"
}

printf 'Starting brightness=%s; dim/medium/bright, then three off/on cycles.\n' "$previous"
sleep 3
step 1 4
step 16 4
step 31 4
for cycle in 1 2 3; do
    printf 'Off/on cycle %s\n' "$cycle"
    step 0 2
    step 31 2
done
