#!/usr/bin/env bash
# Build an uploadable skill bundle (zip with telegram/SKILL.md inside) into dist/.
#
#   scripts/package.sh                                  # public: no secrets at all
#   scripts/package.sh --personal [--env FILE]          # + bot keys only (token, user id, allowlist, proxy)
#   scripts/package.sh --personal --with-account        # + account keys: FULL access to your Telegram
#
# The secrets source defaults to skills/telegram/.env. A personal bundle is for your own
# chat upload only; read "Security model" in the README first.
set -euo pipefail

repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
src="$repo/skills/telegram"
personal="" account="" envfile="$src/.env"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --personal) personal=1 ;;
    --with-account) account=1 ;;
    --env) envfile="$2"; shift ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done
[[ -n "$account" && -z "$personal" ]] && { echo "--with-account needs --personal" >&2; exit 1; }

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
cp -r "$src" "$stage/telegram"
rm -rf "$stage/telegram/.env" "$stage/telegram/.sessions" "$stage/telegram/inbox"

out="$repo/dist/tg-skill.skill"
if [[ -n "$personal" ]]; then
  [[ -f "$envfile" ]] || { echo "no secrets file: $envfile" >&2; exit 1; }
  keys="TELEGRAM_BOT_TOKEN|TELEGRAM_USER_ID|TG_ALLOWED_CHATS|TG_PROXY"
  if [[ -n "$account" ]]; then
    keys="$keys|TELEGRAM_API_ID|TELEGRAM_API_HASH|TELEGRAM_PHONE|TELEGRAM_SESSION_STRING"
    echo "WARNING: bundle includes your account session: anyone holding it can read and write all your chats." >&2
  fi
  grep -E "^($keys)=" "$envfile" > "$stage/telegram/.env" || true
  chmod 600 "$stage/telegram/.env"
  echo "bundled keys: $(cut -d= -f1 "$stage/telegram/.env" | paste -sd' ')" >&2
  out="$repo/dist/tg-skill-personal.skill"
fi

mkdir -p "$repo/dist"
rm -f "$out"
(cd "$stage" && zip -qr "$out" telegram -x '*/__pycache__/*' '*/.DS_Store')
[[ -n "$personal" ]] && chmod 600 "$out"
echo "$out"
