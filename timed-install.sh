#!/usr/bin/env bash
# Optional: runs install.sh with a live elapsed-time counter, so you can see
# (and verify for yourself) how long a real install takes on your server.
# Actual time depends on your network speed and server specs — it isn't
# a guarantee, just a live measurement.
set -Eeuo pipefail

start=$(date +%s)

# Live ticking timer, runs in the background alongside the install.
(
  while true; do
    now=$(date +%s)
    elapsed=$((now - start))
    printf "\r\033[1;36m⏱  %02d:%02d\033[0m " $((elapsed / 60)) $((elapsed % 60))
    sleep 1
  done
) &
timer_pid=$!

cleanup() {
  kill "$timer_pid" 2>/dev/null || true
  wait "$timer_pid" 2>/dev/null || true
}
trap cleanup EXIT

echo -e "\033[1;36m⏱  00:00\033[0m  starting install...\n"

sudo bash install.sh --print-url "$@"
install_status=$?

cleanup
trap - EXIT

end=$(date +%s)
elapsed=$((end - start))

echo -e "\n\033[1;32m✅ Done in ${elapsed} seconds.\033[0m"

exit $install_status
