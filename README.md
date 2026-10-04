# tg-skill

**Telegram for AI agents in one Python file: your account and your bot, with the access level you grant on each call.**

[Русская версия](README.ru.md)

```text
/telegram              → read: unread chats, history, search, channel analysis
/telegram full         → read + send as you (dry-run until confirmed)
/telegram bot          → your bot: notify you, send files, wait for your reply
```

- **Two sides of Telegram in one skill.** Your *account* via [Telethon](https://github.com/LonamiWebs/Telethon) reads everything you can see and writes as you. Your *bot* via the Bot API uses the stdlib only, for notifications, files and remote-control loops.
- **Access you grant per invocation.** `read` is the default. Sending needs `/telegram full`, and every send is a dry-run first that shows the resolved recipient. A `TG_ALLOWED_CHATS` allowlist adds a hard limit.
- **Just Python.** One file, `skills/telegram/scripts/tg.py`. `pip install telethon` is needed only for account mode. No MCP server, no Node, no daemon.
- **Runs anywhere a skill runs.** Claude Code, any Agent Skills–compatible agent, or a hosted chat with code execution (see [where it works](#where-it-works)).

## Quick start

```bash
git clone https://github.com/EZHOWWW/tg-skill && cd tg-skill
ln -s "$PWD/skills/telegram" ~/.claude/skills/telegram     # available in every Claude Code session
pip install telethon

cp skills/telegram/.env.example skills/telegram/.env       # fill in, see comments inside
python3 skills/telegram/scripts/tg.py login                # once: code from Telegram, prints TELEGRAM_SESSION_STRING=...
#   paste that line into skills/telegram/.env
python3 skills/telegram/scripts/tg.py doctor               # {"bot": {"ok": true}, "account": {"ok": true}}
```

Then, in any session:

```text
/telegram            what's unread from my team today?
/telegram            summarize @some_channel since 2026-10-01
/telegram full       answer Alex that I'll send the report tomorrow
/telegram bot        when the tests finish, send me the log
```

## Access modes

| Mode | Allows | Typical use |
|---|---|---|
| `read` (default) | `me`, `chats [--unread]`, `read CHAT [--since/--search]` | triage, search, channel analysis |
| `full` | `read` + `send` as you (text, file, reply) | answering colleagues |
| `bot` | `bot-send`, `bot-file`, `bot-wait` through your bot | notifications, remote control from the phone |

Modes combine: `/telegram full,bot`. The CLI enforces them (`denied: 'send' needs mode 'full'`), and
the skill tells the agent never to raise its own mode. `send` without `--yes` only prints
`{"dry_run": true, "to": "<resolved name>", ...}` and exits 2.

## Commands

```bash
tg.py doctor                                   # what works here (prints var names, never values)
tg.py chats --unread | --query "team"
tg.py read @alice --limit 20
tg.py read -1001234567890 --since 2026-10-01   # whole period, for analysis
tg.py read all --search "invoice"              # global search
tg.py --mode full send @alice "On it" --yes
tg.py --mode full send @alice - --yes < reply.txt
tg.py --mode bot bot-send "Build is green"
tg.py --mode bot bot-file report.pdf --caption "Weekly"
tg.py --mode bot bot-wait --timeout 600        # blocks until you write the bot; files go to inbox/
```

All output is JSON lines, ready for the agent to read or pipe to a file.

**Remote-control loop.** Drive an agent from your phone with no screen. Run `bot-wait`, do
the work, `bot-send` the answer, then `bot-wait` again. Each bot token takes one poller at a time.

## Where it works

| Environment | Bot | Account |
|---|---|---|
| Your machine: Claude Code, Codex CLI, any agent with a shell | ✅ | ✅ |
| Hosted chat sandboxes with code execution (claude.ai, others) | ✅ if `api.telegram.org` is allowed in the sandbox network settings | ⚠️ usually ❌ |

Hosted sandboxes route traffic through an HTTPS proxy with a domain allowlist and block raw
TCP. The Bot API is plain HTTPS and gets through. The account protocol (MTProto) connects
straight to Telegram's IPs and usually cannot. `tg.py doctor` tells you which case you are
in, so you don't have to guess. Upload a bundle built by `scripts/package.sh` (see below).

## Security model

**Read this before you put secrets in a hosted chat.**

| Secret | What a holder can do | How to revoke |
|---|---|---|
| `TELEGRAM_SESSION_STRING` | Everything you can: read all chats, write and delete as you, read login codes (account takeover without 2FA) | Telegram → Settings → Devices → terminate **tg-skill** |
| `TELEGRAM_BOT_TOKEN` | Control that one bot | @BotFather → `/revoke` |
| `TELEGRAM_API_ID` / `API_HASH` | Nothing on their own (they identify your app) | — |
| phone, user id | Personal data | — |

Uploading the secrets file to a hosted chat exposes it in three ways:

1. **Storage.** The provider keeps your skill files under its retention policy.
2. **Transcripts.** Anything the agent prints ends up in chat history and exports.
3. **Prompt injection** (the real one). An agent that reads untrusted chats while holding your secrets and a way to send has all three parts of the [lethal trifecta](https://simonwillison.net/2025/Jun/16/the-lethal-trifecta/). One crafted message in a channel you read can ask it to forward something.

**Verdict.** A bot token in a hosted chat is an acceptable risk: it is scoped to one bot and revoked in seconds. **Your main account's session is not.** Treat uploading it as handing your account to the provider and to anyone who can post in a chat you read.

What tg-skill does about it:

- **`read` by default.** Writes need an explicit `/telegram full`, and every send is a dry-run first.
- **`TG_ALLOWED_CHATS` allowlist.** Writes can go only to the chats you list. This shuts the "send it to @attacker" path.
- **No secret output.** The CLI never prints secrets: bot URLs contain the token and are never echoed, and `doctor` prints variable names only. It refuses to send `.env`, `*.session` and key files.
- **Named session.** The session shows up as **tg-skill** in Devices, so you can kill it without logging out elsewhere.
- **Bot-only bundles by default.** `scripts/package.sh --personal` bundles **bot keys only**. Account keys go in only with `--with-account`, which prints a warning.

What you should do:

- **Separate account for hosted chats.** If you need account mode there, use a second Telegram account and add it only to the chats it needs.
- **2FA on.** Enable two-step verification and *auto-terminate inactive sessions*.
- **Local is safest.** Keep full account mode on your own machine (Claude Code). The secrets file never leaves your disk, and only command output reaches the model.
- **Don't encrypt the file with a password.** The password would have to be typed into the same chat, so it protects nothing.

## Packaging for chat uploads

```bash
scripts/package.sh                                # dist/tg-skill.skill: no secrets (share freely)
scripts/package.sh --personal                     # + bot token, user id, allowlist
scripts/package.sh --personal --with-account      # + account session (read the section above)
```

## Alternatives, and why this exists

Checked in October 2026. All are good projects; none covers *account + bot + Python-only + per-call permissions + works as a plain skill*.

| Project | What it is | Gap for this use case |
|---|---|---|
| [chigwell/telegram-mcp](https://github.com/chigwell/telegram-mcp) (1.7k★) | Python MCP server, 80+ tools, account | MCP, not a skill: a web chat needs a hosted HTTP server and connector support. No bot mode. The large tool surface costs context. (Its `TELEGRAM_EXPOSED_TOOLS=read-only` inspired our modes.) |
| [jackwener/tg-cli](https://github.com/jackwener/tg-cli) (292★) | Python CLI + SKILL.md, local SQLite sync | Account only, no bot. `send` has no confirmation or permission mode. Sync/archive oriented. |
| [devxoul/agent-messenger](https://github.com/devxoul/agent-messenger) (228★) | Multi-messenger CLI, account (TDLib) + bot | Node/Bun plus native TDLib. Credentials live in `~/.config`, so they can't travel into a chat sandbox. No permission gating. |
| [beautyfree/telegram-agent](https://github.com/beautyfree/telegram-agent) | Node CLI + skill (GramJS) | Node 20+, account only, no hard read-only switch. GPL-3.0. |
| [awrshift/skill-telegram](https://github.com/awrshift/skill-telegram) | Python skill (Telethon) | Read-only by design: no sending, no bot. |
| [b1rd33/tg-cli](https://github.com/b1rd33/tg-cli) | Python CLI with strong write gates | Great safety model, but no bot and 62 commands. |
| [Claude Code Telegram channel](https://code.claude.com/docs/en/channels) (official) | Bot bridge into a running Claude Code session | Bot only, Claude Code + Bun only, research preview. It cannot read your chats. |

## Development

```bash
python3 skills/telegram/scripts/test_tg.py     # offline: mode gates, allowlist, dry-runs, doctor
```

CI runs the same checks on Python 3.10 and 3.13, with and without Telethon.

## License

MIT
