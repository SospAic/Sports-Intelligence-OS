#!/usr/bin/env python3
"""从前端入口复现一次账号同步并生成完整 tracelog（stdlib-only）。

忠实复现前端实际请求：login -> csrf -> POST /accounts/{id}/sync -> 轮询。
随后抓取 worker/api 日志 + sync_run_events 时间线 + 最终 run 行。
用法：python scripts/sio_frontend_trace.py <account_id>
"""
import json
import subprocess
import sys
import time
import urllib.request
import urllib.error

TRACE = f"/tmp/sio_trace_{time.strftime('%Y%m%d_%H%M%S')}.log"
buf: list[str] = []


def _write():
    with open(TRACE, "w", encoding="utf-8") as f:
        f.write("\n".join(buf))


def log(msg: str) -> None:
    buf.append(msg)
    print(msg, flush=True)


def sh(cmd):
    try:
        p = subprocess.run(cmd, shell=True, capture_output=True, timeout=120)
        return p.stdout.decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return f"<sh error {e}>"


def http(method, path, token=None, body=None, cookie=None):
    url = API + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("X-CSRF-Token", token)
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read().decode(), r.headers.get("Set-Cookie", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(), e.headers.get("Set-Cookie", "")


API = "http://localhost:8080/api/v1"
ACCT = sys.argv[1] if len(sys.argv) > 1 else "d5e7b227-55d8-40b7-8e92-3c189a249fd8"
EMAIL = "admin@example.com"
PASS = "Admin2026!SIO#Dev"
COMPOSE = "docker compose -f E:/Sports Intelligence OS/docker-compose.yml"
START = time.time()

log(f"TRACE={TRACE}")
log(f"TARGET_ACCOUNT={ACCT}")

# [1] login：同时拿 csrf 与 session cookie
log("=== [1] POST /auth/login (前端登录) ===")
st, out, setck = http("POST", "/auth/login", None, {"email": EMAIL, "password": PASS})
log(f"HTTP {st}")
login = json.loads(out) if out else {}
csrf = login.get("csrf_token", "")
cookie = setck.split(";")[0] if setck else ""
log(f"csrf_len={len(csrf)} cookie_prefix={cookie[:24]}...")

# [2] sync（前端"同步"按钮）
log("=== [2] POST /accounts/%s/sync (前端同步请求) ===" % ACCT)
st, out, _ = http("POST", f"/accounts/{ACCT}/sync", csrf, {}, cookie)
log(f"HTTP {st}")
log(out[:500])
sync = json.loads(out) if out else {}
runid = sync.get("id")
adapter = sync.get("adapter_key")
log(f"RUNID={runid} ADAPTER={adapter} CREATED_STATUS={sync.get('status')}")

if not runid:
    log("!! 未返回 run id（前端会显示同步失败）。worker/api 日志：")
    log(sh(f'{COMPOSE} logs --since 10m worker api 2>/dev/null | grep -iE "error|exception|traceback|csrf|401|403|sync" | tail -40'))
    _write()
    sys.exit(0)

# [3] 轮询
log("=== [3] 轮询 sync-runs ===")
status = ""
for _ in range(40):
    time.sleep(10)
    st, out, _ = http("GET", f"/accounts/{ACCT}/sync-runs?page=1&page_size=1", None, None, cookie)
    item = (json.loads(out).get("items") or [{}])[0]
    status = item.get("status", "")
    elapsed = int(time.time() - START)
    log(f"[t+{elapsed}s] {status}|{item.get('progress_percent')}|{item.get('progress_stage')}|{item.get('error_code') or '-'}|{(item.get('error_message') or '')[:90]}")
    if status in ("success", "degraded", "error", "cancelled"):
        break

# [4] worker/api 适配器层日志
log("=== [4] worker/api 适配器层日志(窗口) ===")
log(sh(f'{COMPOSE} logs --since 30m worker api 2>/dev/null | grep -iE "tiktok|yt-dlp|browser|sync_account|resolve_account|analytics|list_contents|TimeoutError|TransientAdapter|RateLimit|LoginRequired|反爬|未登录|Sign in|net::" | tail -50'))

# [5] sync_run_events 时间线
log("=== [5] sync_run_events 逐步时间线（tracelog 主体） ===")
sql = ("SELECT to_char(created_at,'HH24:MI:SS'), event_type, level, left(message,140) "
       f"FROM sync_run_events WHERE sync_run_id='{runid}' ORDER BY sequence;")
log(sh(f'PGPASSWORD="sio-local-development-only" {COMPOSE} exec -T postgres psql -U sio -d sports_intelligence -t -A -F"|" -c "{sql}" 2>/dev/null'))

# [6] 最终 run 行
log("=== [6] 最终 sync_runs 行 ===")
sql2 = ("SELECT status, error_code, left(error_message,160), left(error_hint,160), "
        "to_char(started_at,'HH24:MI:SS'), to_char(finished_at,'HH24:MI:SS'), progress_percent, progress_stage "
        f"FROM sync_runs WHERE id='{runid}';")
log(sh(f'PGPASSWORD="sio-local-development-only" {COMPOSE} exec -T postgres psql -U sio -d sports_intelligence -t -A -F"|" -c "{sql2}" 2>/dev/null'))

log(f"=== DONE RUNID={runid} TRACE={TRACE} ===")
_write()
