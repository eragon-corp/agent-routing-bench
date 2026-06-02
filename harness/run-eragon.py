#!/usr/bin/env python3
"""
run-eragon.py — Send a skill prompt to the Eragon chat UI via CDP and capture the full response.

Usage:
    python3 run-eragon.py --skill <skill_file> --output <output_file> [--model <model_id>]

Connects to local Chromium CDP on 127.0.0.1:9222, sends the skill to the Eragon
chat UI, waits for completion, captures full response, writes to output_file.
"""

import argparse, json, sys, time, re, urllib.request
from pathlib import Path

try:
    import websocket
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "websocket-client", "-q"], check=True)
    import websocket

CDP_HOST = "127.0.0.1"
CDP_PORT = 9222
DEFAULT_TIMEOUT = 600


def get_targets():
    with urllib.request.urlopen(f"http://{CDP_HOST}:{CDP_PORT}/json", timeout=10) as r:
        return json.loads(r.read())


def find_eragon_tab(targets):
    for t in targets:
        if t.get("type") == "page" and "eragon.ai" in t.get("url", ""):
            return t
    return None


def evaluate(ws, expression, await_promise=False):
    mid = int(time.time() * 1000) % 100000
    ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                        "params": {"expression": expression, "returnByValue": True, "awaitPromise": await_promise}}))
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            r = json.loads(ws.recv())
        except Exception:
            break
        if r.get("id") == mid:
            return r.get("result", {}).get("result", {}).get("value")
    return None


def navigate(ws, url):
    mid = int(time.time() * 1000) % 100000 + 1
    ws.send(json.dumps({"id": mid, "method": "Page.navigate", "params": {"url": url}}))
    deadline = time.time() + 15
    while time.time() < deadline:
        try:
            r = json.loads(ws.recv())
        except Exception:
            break
        if r.get("id") == mid:
            return


def send_message(ws, text):
    js = f"""(function(){{
        var setter=Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype,\'value\').set;
        var ta=document.querySelector(\'textarea\');
        setter.call(ta,{json.dumps(text)});
        ta.dispatchEvent(new Event(\'input\',{{bubbles:true}}));
        ta.focus();
        var btn=document.querySelector(\'button[title="Send"]\');
        if(btn) btn.dispatchEvent(new MouseEvent(\'click\',{{bubbles:true,cancelable:true,view:window}}));
        return \'sent:\'+ta.value.length;
    }})()"""
    return evaluate(ws, js)


def run(skill_file, output_file, model_override, timeout):
    content = Path(skill_file).read_text()
    # Strip YAML frontmatter
    content = re.sub(r"^---\n.*?\n---\n", "", content, flags=re.DOTALL).strip()

    targets = get_targets()
    tab = find_eragon_tab(targets)
    if not tab:
        print("ERROR: No Eragon chat tab found", file=sys.stderr)
        return 1

    print(f"Tab: {tab[\'url\']}", flush=True)
    ws = websocket.create_connection(tab["webSocketDebuggerUrl"], timeout=30)
    try:
        # Fresh session
        hostname = evaluate(ws, "window.location.hostname") or ""
        navigate(ws, f"https://{hostname}/chat")
        time.sleep(4)

        # Model override for eragon-norouting
        if model_override:
            send_message(ws, f"/model {model_override}")
            time.sleep(5)

        # Send skill
        sent = send_message(ws, content)
        print(f"Sent: {sent}", flush=True)

        # Wait for completion
        start = time.time()
        stop_seen = False
        stop_gone_since = None
        while time.time() - start < timeout:
            has_stop = evaluate(ws, "!!document.querySelector(\'button[title=\"Stop\"]\')") 
            if has_stop:
                stop_seen = True
                stop_gone_since = None
                elapsed = int(time.time() - start)
                if elapsed % 60 == 0:
                    print(f"  Running... {elapsed}s", flush=True)
            else:
                if stop_seen:
                    if stop_gone_since is None:
                        stop_gone_since = time.time()
                    elif time.time() - stop_gone_since >= 4:
                        break
            time.sleep(2)
        else:
            print(f"ERROR: Timed out after {timeout}s", file=sys.stderr)
            return 1

        elapsed = int(time.time() - start)
        print(f"Done in {elapsed}s", flush=True)

        # Capture response
        text = evaluate(ws, """(function(){
            var msgs=[...document.querySelectorAll(\'[class*="message"]\')];
            if(msgs.length) return msgs[msgs.length-1].innerText;
            return document.body.innerText.slice(-30000);
        })()""") or ""
        Path(output_file).write_text(text)
        print(f"Written {len(text)} chars to {output_file}", flush=True)
        return 0
    finally:
        ws.close()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--skill", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--model", default=None)
    p.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = p.parse_args()
    sys.exit(run(args.skill, args.output, args.model, args.timeout))


if __name__ == "__main__":
    main()
