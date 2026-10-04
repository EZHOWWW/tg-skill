"""Offline checks of the access guards and helpers: python3 scripts/test_tg.py"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tg  # noqa: E402

assert tg.chunks("a" * 9000) == ["a" * 4000, "a" * 4000, "a" * 1000]
assert tg.chunks("") == [""]
assert tg.peer("-100123") == -100123 and tg.peer("@x") == "@x" and tg.peer("all") is None
for bad in (".env", "x.session", "id_rsa", "k.PEM"):
    try:
        tg.refuse_secret_file(bad)
        raise AssertionError(bad)
    except SystemExit:
        pass
tg.refuse_secret_file("report.pdf")


def denied(fn, *args):
    try:
        fn(*args)
        return False
    except SystemExit:
        return True


m = tg.check_mode
assert not denied(m, "read", "read") and not denied(m, "full", "chats") and not denied(m, "read", "login")
assert not denied(m, "read", "doctor")
assert denied(m, "read", "send") and denied(m, "bot", "send") and denied(m, "read", "bot-send") and denied(m, "bot", "read")
assert denied(m, "read", "bot-file") and denied(m, "full", "bot-wait")
assert not denied(m, "full", "send") and not denied(m, "bot", "bot-wait") and not denied(m, "full,bot", "bot-send")
assert denied(m, "god", "read")

os.environ["TG_ALLOWED_CHATS"] = "@Alice, -100123"
assert not denied(tg.check_allowed, "alice") and not denied(tg.check_allowed, "x", -100123)
assert denied(tg.check_allowed, "@bob", 42)
del os.environ["TG_ALLOWED_CHATS"]
assert not denied(tg.check_allowed, "@bob")


def run(*args, **extra):
    env = {k: v for k, v in os.environ.items() if not k.startswith(("TELEGRAM_", "TG_"))}
    env.update(TELEGRAM_BOT_TOKEN="1:x", TELEGRAM_USER_ID="1", HTTPS_PROXY="http://127.0.0.1:1", **extra)
    return subprocess.run([sys.executable, tg.__file__, *args], env=env, capture_output=True, text=True)


# writes to anyone but the owner stop at the guard before any network call
r = run("--mode", "bot", "bot-send", "hi", "--chat", "2")
assert r.returncode == 2 and '"dry_run": true' in r.stdout, (r.returncode, r.stdout, r.stderr)
r = run("--mode", "bot", "bot-file", __file__, "--chat", "2")
assert r.returncode == 2 and '"dry_run": true' in r.stdout, (r.returncode, r.stdout, r.stderr)
r = run("--mode", "bot", "bot-send", "hi", "--chat", "2", "--yes", TG_ALLOWED_CHATS="3")
assert r.returncode == 1 and "TG_ALLOWED_CHATS" in r.stderr, (r.returncode, r.stdout, r.stderr)
r = run("--mode", "bot", "bot-file", "/tmp/.env")
assert r.returncode == 1 and "refused" in r.stderr, (r.returncode, r.stdout, r.stderr)
r = run("send", "@x", "hi", "--yes")
assert r.returncode == 1 and "denied" in r.stderr, (r.returncode, r.stdout, r.stderr)

# doctor never crashes offline and never prints secret values
r = run("doctor")
report = json.loads(r.stdout)
assert r.returncode == 0 and report["bot"]["ok"] is False and report["account"]["ok"] is False, r
assert "1:x" not in r.stdout + r.stderr
print("ok")
