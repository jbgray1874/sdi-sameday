"""Keeps the phone link for SDI Same Day Intelligence (was Brief Lite) alive while this laptop is on.

Run by Studio_Brief_Autostart.bat every 5 minutes. If no tunnel to port 5020 is running, it starts one
(Cloudflare quick tunnel, free, HTTPS - phones need HTTPS for the mic) and writes the link to
brief_lite\\PHONE_LINK.txt. A running tunnel is left alone, so the link only changes after a restart.
Phones still need the team access code (LITE_ACCESS_CODE in .env) - this PC doesn't.
"""
import os, re, subprocess, time

HERE = os.path.dirname(os.path.abspath(__file__))
EXE = os.path.join(os.path.dirname(HERE), "newsys", "tools", "cloudflared.exe")
LOG = os.path.join(HERE, "tunnel.log")
LINK = os.path.join(HERE, "PHONE_LINK.txt")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def running():
    """Is a cloudflared already pointing at Brief Lite (5020)? The WhatsApp tunnel (5099) doesn't count."""
    out = subprocess.run(["powershell", "-NoProfile", "-Command",
                          "Get-CimInstance Win32_Process -Filter \"name='cloudflared.exe'\" | % CommandLine"],
                         capture_output=True, text=True, creationflags=NOWIN).stdout
    return "127.0.0.1:5020" in out


def link():
    try:
        m = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", open(LOG, encoding="utf-8", errors="ignore").read())
        return m[-1] if m else ""
    except OSError:
        return ""


def alive(url):
    """Does the tunnel actually answer? 14 Oct 2026: cloudflared kept running for hours after Cloudflare dropped the quick
    tunnel ("Unauthorized: Tunnel not found"), so 'a process is running' wasn't enough - ask the link itself."""
    import urllib.request
    try:
        return urllib.request.urlopen(url.rstrip("/") + "/sw.js", timeout=12).status == 200
    except Exception:
        return False


def dead_in_log():
    try:
        tail = open(LOG, encoding="utf-8", errors="ignore").read()[-6000:]
    except OSError:
        return False
    return "Tunnel not found" in tail and tail.rfind("Tunnel not found") > tail.rfind("Registered tunnel connection")


def main():
    if running() and link() and (dead_in_log() or not alive(link())):
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"name='cloudflared.exe'\" | ? { $_.CommandLine -like '*5020*' } | "
                        "% { Stop-Process -Id $_.ProcessId -Force }"], creationflags=NOWIN)
        time.sleep(2)
    if running() and not link():
        # started but never got its address (e.g. a network that blocks Cloudflare's port 7844): start it again,
        # so it connects by itself as soon as the laptop is on a network that allows it
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Get-CimInstance Win32_Process -Filter \"name='cloudflared.exe'\" | ? { $_.CommandLine -like '*5020*' } | "
                        "% { Stop-Process -Id $_.ProcessId -Force }"], creationflags=NOWIN)
        time.sleep(2)
    if not running():
        log = open(LOG, "w", encoding="utf-8")
        subprocess.Popen([EXE, "tunnel", "--no-autoupdate", "--protocol", "http2", "--url", "http://127.0.0.1:5020"],
                         stdout=log, stderr=log, creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0))
        for _ in range(30):
            time.sleep(1)
            if link():
                break
    url = link()
    if url:
        open(LINK, "w", encoding="utf-8").write(
            f"SDI Same Day Intelligence on phones: {url}\n"
            "iPhone: open in Safari > Share > Add to Home Screen.  Android: open in Chrome > Install app.\n"
            "The team access code is LITE_ACCESS_CODE in C:\\SDI_Automation\\.env\n"
            "This link changes only when the laptop or the tunnel restarts.\n")
    fixed = None
    if url:   # the never-changing link (fixed_link.py) follows today's tunnel
        try:
            import fixed_link
            fixed = fixed_link.update(url)
        except Exception as e:
            print("fixed link not updated:", str(e)[:120])
    if fixed:
        with open(LINK, "a", encoding="utf-8") as f:
            f.write(f"\nFIXED LINK (never changes - give this one to people): {fixed}\n")
    print(fixed or url or "no link yet")


if __name__ == "__main__":
    main()
