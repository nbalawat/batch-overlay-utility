#!/usr/bin/env bash
# The cloud machine's own control command. Cloud-init installs it as /usr/local/bin/batchiq and runs
# `batchiq provision` once; after that, from a laptop:  ssh batchiq batchiq status
#
#   batchiq status            service state, containers, whether the console answers, when the machine stops itself
#   batchiq wait [MINUTES]    block until the console answers /api/meta (default 30 minutes)
#   batchiq logs [SERVICE]    follow the stack's logs (all services, or one: api, ui)
#   batchiq restart           rebuild if needed and restart the stack
#   batchiq update [REF]      fetch REF (default: the configured one) from Git and restart on it
#   batchiq env KEY=VALUE     set a value in the stack's .env (for example ANTHROPIC_API_KEY); restart to apply
#   batchiq extend [HOURS]    push the automatic stop back to HOURS from now (default: the configured hours)
#   batchiq reset --yes       delete every container and image, then build and start again from scratch
#
# Settings live in /etc/batchiq/machine.env (written by cloud-init from the OpenTofu variables).
set -euo pipefail

CONF="${BATCHIQ_CONF:-/etc/batchiq/machine.env}"
# shellcheck source=/dev/null
[ -f "$CONF" ] && . "$CONF"
SRC="${BATCHIQ_SRC:-/opt/batchiq/src}"
GIT_URL="${GIT_URL:-https://github.com/nbalawat/batch-overlay-utility.git}"
GIT_REF="${GIT_REF:-main}"
AUTO_STOP_HOURS="${AUTO_STOP_HOURS:-10}"
OWNER="${OWNER:-batchiq}"
SYSTEMCTL="${SYSTEMCTL:-systemctl}"
SHUTDOWN="${SHUTDOWN:-shutdown}"
READY_URL="${READY_URL:-http://localhost:8080/api/meta}"

say() { printf '%s\n' "$*"; }
die() { printf 'batchiq: %s\n' "$*" >&2; exit 1; }
# Git as the checkout's owner: root may not read a repository another user owns ("dubious ownership").
git_as_owner() { if [ "$(id -un)" = "$OWNER" ]; then git "$@"; else sudo -u "$OWNER" git "$@"; fi; }
# Re-run as root through sudo once; BATCHIQ_ESCALATED stops a loop if sudo does not make us root.
# BATCHIQ_SKIP_ROOT=1 runs as the current user (the unit tests, with systemctl and shutdown stubbed).
need_root() {
  [ "$(id -u)" -eq 0 ] || [ "${BATCHIQ_SKIP_ROOT:-0}" = 1 ] && return 0
  [ "${BATCHIQ_ESCALATED:-0}" = 1 ] && die "needs root, and sudo did not provide it"
  exec sudo -E BATCHIQ_ESCALATED=1 "$0" "$@"
}

set_conf() {  # set_conf KEY VALUE: replace or append KEY=VALUE in the settings file
  local key="$1" value="$2"
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] || die "bad setting name: $key"
  if grep -q "^${key}=" "$CONF" 2>/dev/null; then
    sed -i "s|^${key}=.*|${key}=${value}|" "$CONF"
  else
    printf '%s=%s\n' "$key" "$value" >> "$CONF"
  fi
}

install_docker() {
  command -v docker >/dev/null && docker compose version >/dev/null 2>&1 && return 0
  # Docker's own apt repository: Ubuntu's docker.io lags behind on Compose features the stack uses (--wait).
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  # shellcheck source=/dev/null
  . /etc/os-release
  printf 'deb [arch=%s signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$(dpkg --print-architecture)" "$VERSION_CODENAME" > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  DEBIAN_FRONTEND=noninteractive apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  $SYSTEMCTL enable --now docker
}

fetch_source() {
  local ref="${1:-$GIT_REF}"
  if [ ! -d "$SRC/.git" ]; then
    install -d -o "$OWNER" -g "$OWNER" "$(dirname "$SRC")"
    git_as_owner clone --quiet "$GIT_URL" "$SRC"
  fi
  git_as_owner -C "$SRC" fetch --quiet --prune origin "+refs/heads/*:refs/remotes/origin/*" "+refs/tags/*:refs/tags/*"
  # A branch name follows its remote; a tag or commit is checked out as is.
  if git_as_owner -C "$SRC" rev-parse --verify --quiet "refs/remotes/origin/$ref" >/dev/null; then
    git_as_owner -C "$SRC" checkout --quiet -B "$ref" "origin/$ref"
  else
    git_as_owner -C "$SRC" checkout --quiet --detach "$ref"
  fi
  say "source: $ref at $(git_as_owner -C "$SRC" rev-parse --short HEAD)"
}

schedule_stop() {  # schedule_stop HOURS: 0 turns the automatic stop off
  local hours="${1:-$AUTO_STOP_HOURS}"
  [[ "$hours" =~ ^[0-9]+$ ]] || die "hours must be a whole number: $hours"
  $SHUTDOWN -c 2>/dev/null || true
  if [ "$hours" -gt 0 ]; then
    $SHUTDOWN -h "+$((hours * 60))" "BatchIQ stops itself after ${hours}h; run 'batchiq extend' to keep it on" >/dev/null 2>&1
    say "the machine stops itself in ${hours}h (disk and data are kept)"
  else
    say "automatic stop is off: the machine runs until you stop it"
  fi
}

stop_time() {
  local f=/run/systemd/shutdown/scheduled usec
  [ -f "$f" ] || { say "not scheduled"; return; }
  usec="$(sed -n 's/^USEC=//p' "$f")"
  date -d "@$((usec / 1000000))" '+%Y-%m-%d %H:%M %Z'
}

ready() { curl -fsS -m 5 -o /dev/null "$READY_URL"; }

cmd_provision() {
  need_root provision "$@"
  install_docker
  usermod -aG docker "$OWNER"
  fetch_source
  $SYSTEMCTL daemon-reload
  $SYSTEMCTL enable batchiq.service batchiq-autostop.service
  $SYSTEMCTL start batchiq-autostop.service
  $SYSTEMCTL start --no-block batchiq.service
  say "provisioned: the demo is starting (the first start builds both images, about 5 minutes)"
}

cmd_run() {  # the service's ExecStart: the same compose file a laptop runs, in the foreground
  cd "$SRC"
  exec docker compose up --build --remove-orphans
}

cmd_halt() {  # the service's ExecStop: stop the containers, keep the images
  cd "$SRC"
  docker compose stop --timeout 30
}

cmd_status() {
  say "ref:        $GIT_REF (commit $(git_as_owner -C "$SRC" rev-parse --short HEAD 2>/dev/null || echo none))"
  say "service:    $($SYSTEMCTL is-active batchiq.service 2>/dev/null || true)"
  if ready 2>/dev/null; then say "console:    ready on http://localhost:8080"; else say "console:    not answering yet"; fi
  if [ -f "$SRC/.env" ] && grep -q '^ANTHROPIC_API_KEY=.' "$SRC/.env"; then say "assistant:  Claude (ANTHROPIC_API_KEY is set)"
  else say "assistant:  offline rules (set ANTHROPIC_API_KEY for conversational answers)"; fi
  say "auto stop:  $(stop_time)"
  say "disk:       $(df -h / | awk 'NR==2 {print $3 " used of " $2}')"
  say "memory:     $(free -m | awk '/^Mem:/ {print $3 " MB used of " $2 " MB"}')"
  say ""
  (cd "$SRC" && docker compose ps --format 'table {{.Service}}\t{{.Status}}') 2>/dev/null || true
}

cmd_wait() {
  local minutes="${1:-30}" deadline
  [[ "$minutes" =~ ^[0-9]+$ ]] || die "minutes must be a whole number: $minutes"
  deadline=$(( $(date +%s) + minutes * 60 ))
  until ready 2>/dev/null; do
    [ "$(date +%s)" -lt "$deadline" ] || die "the console did not answer within ${minutes} minutes; see: batchiq logs"
    sleep "${WAIT_INTERVAL:-10}"
  done
  say "ready"
}

cmd_logs() { cd "$SRC" && exec docker compose logs --follow --tail 200 "$@"; }

cmd_restart() { need_root restart "$@"; $SYSTEMCTL restart batchiq.service; say "restarting the demo"; }

cmd_update() {
  need_root update "$@"
  local ref="${1:-$GIT_REF}"
  [[ "$ref" =~ ^[A-Za-z0-9._/-]{1,200}$ ]] || die "not a branch, tag or commit: $ref"
  fetch_source "$ref"
  # This command itself comes from the source too, so an update brings its new subcommands.
  install -m 0755 "$SRC/infra/modules/common/machine-bootstrap/files/batchiq.sh" "${BATCHIQ_BIN:-/usr/local/bin/batchiq}"
  set_conf GIT_REF "$ref"
  $SYSTEMCTL restart batchiq.service
}

cmd_env() {
  local pair="${1:?usage: batchiq env KEY=VALUE}" key
  key="${pair%%=*}"
  [[ "$key" =~ ^[A-Z_][A-Z0-9_]*$ ]] && [[ "$pair" == *=* ]] || die "expected KEY=VALUE"
  touch "$SRC/.env" && chmod 600 "$SRC/.env"
  if grep -q "^${key}=" "$SRC/.env"; then
    grep -v "^${key}=" "$SRC/.env" > "$SRC/.env.tmp" || true
    mv "$SRC/.env.tmp" "$SRC/.env"; chmod 600 "$SRC/.env"
  fi
  printf '%s\n' "$pair" >> "$SRC/.env"
  say "set $key in the stack's .env; run 'batchiq restart' to apply"
}

cmd_extend() { need_root extend "$@"; schedule_stop "${1:-$AUTO_STOP_HOURS}"; }

cmd_reset() {
  [ "${1:-}" = "--yes" ] || die "this deletes every container and image of the demo; run: batchiq reset --yes"
  need_root reset "$@"
  $SYSTEMCTL stop batchiq.service
  (cd "$SRC" && docker compose down --rmi local --remove-orphans)
  $SYSTEMCTL start batchiq.service
  say "reset: the demo builds and starts again from scratch"
}

main() {
  local cmd="${1:-status}"
  shift || true
  case "$cmd" in
    provision|run|halt|status|wait|logs|restart|update|env|extend|reset) "cmd_$cmd" "$@" ;;
    autostop) need_root autostop "$@"; schedule_stop "$AUTO_STOP_HOURS" ;;
    help|-h|--help) sed -n '2,/^set -euo/p' "$0" | sed '$d; s/^# \{0,1\}//' ;;
    *) die "unknown command '$cmd' (try: batchiq help)" ;;
  esac
}

[ "${BATCHIQ_SOURCE_ONLY:-0}" = 1 ] || main "$@"
