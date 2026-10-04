#!/usr/bin/env python3
"""tg-skill: Telegram for agents. Your account (Telethon) + your bot (Bot API, stdlib only).

Access is granted per call with --mode: read (default) | full (read + send) | bot,
comma-separable (full,bot). Sending as you also needs --yes; without it you get a
dry-run and exit code 2. Config: env vars or <skill>/.env. Output: JSON lines.

    tg.py doctor                                   # what works in this environment
    tg.py login                                    # once, interactive -> TELEGRAM_SESSION_STRING
    tg.py me
    tg.py chats [--query q] [--unread] [--limit 50]
    tg.py read CHAT [--limit 20] [--search q] [--since YYYY-MM-DD]   # CHAT: @user | id | +phone | me | all
    tg.py --mode full send CHAT "text" [--file F] [--reply-to ID] --yes  # text "-" = stdin
    tg.py --mode bot bot-send "text" [--chat ID --yes]        # default chat: TELEGRAM_USER_ID
    tg.py --mode bot bot-file PATH [--caption c] [--chat ID --yes]
    tg.py --mode bot bot-wait [--timeout 300]       # block until the owner writes the bot
"""
import argparse
import asyncio
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
INBOX = ROOT / "inbox"  # files the owner sends to the bot land here
LIMIT = 4000  # Telegram max is 4096
KEYS = ("TELEGRAM_API_ID", "TELEGRAM_API_HASH", "TELEGRAM_PHONE", "TELEGRAM_SESSION_STRING",
        "TELEGRAM_BOT_TOKEN", "TELEGRAM_USER_ID", "TG_ALLOWED_CHATS", "TG_PROXY")
NEEDS = {"me": "read", "chats": "read", "read": "read", "send": "full",
         "bot-send": "bot", "bot-file": "bot", "bot-wait": "bot"}


def load_env():
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))


def env(key):
    v = os.environ.get(key)
    if not v:
        sys.exit(f"error: {key} is not set (env or {ROOT / '.env'})")
    return v


def out(obj):
    print(json.dumps(obj, ensure_ascii=False, default=str), flush=True)


def chunks(text):
    return [text[i:i + LIMIT] for i in range(0, len(text), LIMIT)] or [""]


def refuse_secret_file(path):
    n = Path(path).name.lower()
    if n.startswith(".env") or n.endswith((".session", ".pem", ".key")) or n in ("id_rsa", "id_ed25519"):
        sys.exit(f"refused: {n} looks like a secret, not sending it")


def check_allowed(*refs):
    """TG_ALLOWED_CHATS (comma list of @usernames / ids) limits where writes may go."""
    raw = os.environ.get("TG_ALLOWED_CHATS")
    if not raw:
        return
    allow = {x.strip().lower().lstrip("@") for x in raw.split(",") if x.strip()}
    if not allow & {str(r).lower().lstrip("@") for r in refs if r is not None}:
        sys.exit(f"denied: {refs[0]} is not in TG_ALLOWED_CHATS")


def check_mode(mode, cmd):
    have = set(mode.split(","))
    if not have <= {"read", "full", "bot"}:
        sys.exit(f"error: unknown mode {mode!r}; use read|full|bot")
    need = NEEDS.get(cmd)
    if need and need not in have and not (need == "read" and "full" in have):
        sys.exit(f"denied: '{cmd}' needs mode '{need}', current mode is '{mode}'. "
                 f"Ask the user to invoke /telegram {need}")


# ---- bot (Bot API, stdlib) --------------------------------------------------

def _bot_request(method, data, content_type, timeout=30):
    # HTTPS_PROXY from the environment is honoured by urllib.
    url = f"https://api.telegram.org/bot{env('TELEGRAM_BOT_TOKEN')}/{method}"
    req = urllib.request.Request(url, data, {"Content-Type": content_type})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as f:
            return json.load(f)["result"]
    except urllib.error.HTTPError as e:  # never print e.url: it contains the token
        sys.exit(f"bot api error {e.code}: {e.read().decode()[:300]}")
    except urllib.error.URLError as e:
        sys.exit(f"bot api unreachable: {e.reason}")


def bot(method, **params):
    params = {k: v for k, v in params.items() if v is not None}
    return _bot_request(method, json.dumps(params).encode(), "application/json", params.get("timeout", 0) + 30)


def bot_upload(method, field, path, **params):
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
             for k, v in params.items() if v is not None]
    name = Path(path).name.replace('"', "")
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{field}"; filename="{name}"\r\n'
                 f"Content-Type: application/octet-stream\r\n\r\n".encode() + Path(path).read_bytes()
                 + f"\r\n--{b}--\r\n".encode())
    return _bot_request(method, b"".join(parts), f"multipart/form-data; boundary={b}", 120)


def bot_download(file_id, name):
    path = bot("getFile", file_id=file_id)["file_path"]  # Bot API caps downloads at 20 MB
    INBOX.mkdir(exist_ok=True)
    target = INBOX / (Path(name).name or file_id)
    url = f"https://api.telegram.org/file/bot{env('TELEGRAM_BOT_TOKEN')}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=120) as f:
            target.write_bytes(f.read())
    except urllib.error.URLError as e:  # message only, the URL carries the token
        sys.exit(f"bot file download failed: {getattr(e, 'code', '')} {getattr(e, 'reason', '')}")
    return str(target)


def bot_target(a):
    owner = env("TELEGRAM_USER_ID")
    chat = a.chat or owner
    if str(chat) != owner:
        check_allowed(chat)
        if not a.yes:
            out({"dry_run": True, "via": "bot", "to": chat, "text": getattr(a, "text", None),
                 "file": getattr(a, "path", None)})
            sys.exit(2)
    return chat


def bot_send(a):
    chat = bot_target(a)
    ids = [bot("sendMessage", chat_id=chat, text=t, disable_web_page_preview=True)["message_id"]
           for t in chunks(a.text)]
    out({"sent": ids})


def bot_file(a):
    refuse_secret_file(a.path)
    chat = bot_target(a)
    out({"sent": bot_upload("sendDocument", "document", a.path, chat_id=chat, caption=a.caption)["message_id"]})


def bot_wait(a):
    owner, offset, end = int(env("TELEGRAM_USER_ID")), None, time.time() + a.timeout
    # ponytail: plain long-poll; one poller per token (409 = another bridge is polling it)
    while time.time() < end:
        for u in bot("getUpdates", offset=offset, timeout=25, allowed_updates=["message"]):
            offset = u["update_id"] + 1
            m = u.get("message", {})
            if m.get("from", {}).get("id") != owner:
                continue
            item = {"message_id": m["message_id"], "date": m["date"], "text": m.get("text") or m.get("caption")}
            if doc := m.get("document"):
                item["file"] = bot_download(doc["file_id"], doc.get("file_name") or doc["file_id"])
            elif m.get("photo"):
                item["file"] = bot_download(m["photo"][-1]["file_id"], m["photo"][-1]["file_id"] + ".jpg")
            if item["text"] or "file" in item:
                bot("getUpdates", offset=offset, timeout=0)  # ack so it isn't redelivered
                return out(item)
    sys.exit("timeout: no message")


# ---- user account (Telethon) ----------------------------------------------

def client(fresh=False):
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    s = os.environ.get("TELEGRAM_SESSION_STRING")
    if fresh or s:
        session = StringSession("" if fresh else s)
    else:
        (ROOT / ".sessions").mkdir(exist_ok=True)
        session = str(ROOT / ".sessions" / "user")
    proxy = None
    if p := os.environ.get("TG_PROXY"):  # http://host:port or socks5://..., needs python-socks
        u = urllib.parse.urlparse(p)
        kind = {"https": "http", "socks5h": "socks5"}.get(u.scheme, u.scheme)
        proxy = (kind, u.hostname, u.port, True, u.username, u.password)
    # device_model names this session in Settings -> Devices, so it can be terminated on its own
    return TelegramClient(session, int(env("TELEGRAM_API_ID")), env("TELEGRAM_API_HASH"),
                          proxy=proxy, device_model="tg-skill")


def peer(x):
    return None if x == "all" else int(x) if x.lstrip("-").isdigit() else x


def name_of(e):
    if e is None:
        return None
    return getattr(e, "title", None) or " ".join(
        filter(None, [getattr(e, "first_name", None), getattr(e, "last_name", None)])) or getattr(e, "username", None)


def msg(m):
    return {"id": m.id, "chat": m.chat_id, "date": m.date.isoformat(), "out": m.out,
            "sender": m.sender_id, "from": name_of(m.sender), "text": m.raw_text,
            "reply_to": m.reply_to_msg_id, "media": type(m.media).__name__ if m.media else None}


async def user_cmd(a):
    from telethon import utils
    from telethon.sessions import StringSession

    c = client(fresh=a.cmd == "login")
    await c.connect()
    try:
        if a.cmd == "login":
            await c.start(phone=env("TELEGRAM_PHONE"))  # asks for the code / 2FA password on stdin
            print("TELEGRAM_SESSION_STRING=" + StringSession.save(c.session))
            print("# full access to your account: keep it as secret as the password", file=sys.stderr)
            return
        if not await c.is_user_authorized():
            sys.exit("error: not logged in. Run `tg.py login` yourself and put the printed line in .env")
        if a.cmd == "me":
            me = await c.get_me()
            out({"id": me.id, "username": me.username, "name": name_of(me), "phone": me.phone})
        elif a.cmd == "chats":
            async for d in c.iter_dialogs(limit=a.limit):
                if (not a.query or a.query.lower() in d.name.lower()) and (not a.unread or d.unread_count):
                    out({"id": d.id, "title": d.name, "unread": d.unread_count,
                         "username": getattr(d.entity, "username", None),
                         "kind": "channel" if d.is_channel and not d.is_group else "group" if d.is_group else "user"})
        elif a.cmd == "read":
            since = datetime.fromisoformat(a.since).replace(tzinfo=timezone.utc) if a.since else None
            limit = a.limit if a.limit is not None else (None if since else 20)
            async for m in c.iter_messages(peer(a.chat), limit=limit, search=a.search):
                if since and m.date < since:
                    break
                out(msg(m))
        elif a.cmd == "send":
            if not a.text and not a.file:
                sys.exit("error: nothing to send")
            target = await c.get_entity(peer(a.chat))
            if not getattr(target, "is_self", False):
                check_allowed(a.chat, utils.get_peer_id(target), getattr(target, "username", None))
            if not a.yes:
                out({"dry_run": True, "to": name_of(target), "id": utils.get_peer_id(target),
                     "text": a.text, "file": a.file})
                sys.exit(2)
            if a.file:
                refuse_secret_file(a.file)
                sent = [await c.send_file(target, a.file, caption=a.text)]
            else:
                sent = [await c.send_message(target, t, reply_to=a.reply_to) for t in chunks(a.text)]
            out({"sent": [m.id for m in sent], "to": name_of(target)})
    finally:
        await c.disconnect()


# ---- doctor -----------------------------------------------------------------

async def _doctor_account():
    c = client()
    try:
        await asyncio.wait_for(c.connect(), 15)
        authorized = await c.is_user_authorized()
        return {"ok": authorized, "connected": True,
                **({} if authorized else {"hint": "run `tg.py login` locally"})}
    finally:
        await c.disconnect()


def doctor():
    report = {"env_file": (ROOT / ".env").exists(), "set": [k for k in KEYS if os.environ.get(k)]}
    try:
        report["bot"] = {"ok": True, "bot": "@" + bot("getMe")["username"]}
    except SystemExit as e:
        report["bot"] = {"ok": False, "error": str(e)}
    try:
        import telethon  # noqa: F401
        report["account"] = asyncio.run(_doctor_account())
    except ImportError:
        report["account"] = {"ok": False, "error": "telethon missing: pip install telethon"}
    except SystemExit as e:
        report["account"] = {"ok": False, "error": str(e)}
    except Exception as e:  # noqa: BLE001 - reporting it is the point
        report["account"] = {"ok": False, "error": f"{type(e).__name__}: {str(e)[:200]}",
                             "hint": "MTProto needs raw TCP to Telegram; hosted sandboxes often allow only HTTPS"}
    out(report)


def main():
    load_env()
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--mode", default=os.environ.get("TG_MODE", "read"))
    s = p.add_subparsers(dest="cmd", required=True)
    s.add_parser("doctor")
    s.add_parser("login")
    s.add_parser("me")
    x = s.add_parser("chats")
    x.add_argument("--query")
    x.add_argument("--unread", action="store_true")
    x.add_argument("--limit", type=int, default=50)
    x = s.add_parser("read")
    x.add_argument("chat")
    x.add_argument("--limit", type=int)
    x.add_argument("--search")
    x.add_argument("--since")
    x = s.add_parser("send")
    x.add_argument("chat")
    x.add_argument("text", nargs="?", default="")
    x.add_argument("--file")
    x.add_argument("--reply-to", type=int)
    x.add_argument("--yes", action="store_true")
    x = s.add_parser("bot-send")
    x.add_argument("text")
    x.add_argument("--chat")
    x.add_argument("--yes", action="store_true")
    x = s.add_parser("bot-file")
    x.add_argument("path")
    x.add_argument("--caption")
    x.add_argument("--chat")
    x.add_argument("--yes", action="store_true")
    x = s.add_parser("bot-wait")
    x.add_argument("--timeout", type=int, default=300)
    a = p.parse_args()
    check_mode(a.mode, a.cmd)
    if getattr(a, "text", None) == "-":
        a.text = sys.stdin.read()
    if a.cmd == "doctor":
        doctor()
    elif a.cmd in ("bot-send", "bot-file", "bot-wait"):
        {"bot-send": bot_send, "bot-file": bot_file, "bot-wait": bot_wait}[a.cmd](a)
    else:
        asyncio.run(user_cmd(a))


if __name__ == "__main__":
    main()
