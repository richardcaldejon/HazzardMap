from flask import Flask, render_template, jsonify, make_response, Response, stream_with_context, send_from_directory
import json
import os
from datetime import datetime
import subprocess
import threading
import time
import queue

app = Flask(__name__)

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DATA_FILE   = os.path.join(BASE_DIR, "history.json")
STATUS_FILE = os.path.join(BASE_DIR, "status.json")

# ----------------------------
# SSE CLIENT REGISTRY
# Each connected browser gets its own queue
# ----------------------------
_clients = []
_clients_lock = threading.Lock()

def broadcast(data):
    """Push new data to all connected SSE clients."""
    payload = json.dumps(data)
    with _clients_lock:
        dead = []
        for q in _clients:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _clients.remove(q)


# ----------------------------
# LOAD DATA
# ----------------------------
def load_data():
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    data.sort(key=lambda x: x.get("time", 0), reverse=True)
    return data


# ----------------------------
# UPDATE STATUS
# ----------------------------
def update_status(state: bool):
    status = {
        "API_ONLINE": state,
        "last_update": datetime.now().isoformat()
    }
    with open(STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(status, f, indent=2)


# ----------------------------
# RUN ONE SCRIPT
# ----------------------------
def run_step(script_path):
    full_path = os.path.join(BASE_DIR, script_path)
    print(f"▶ Running {full_path}")
    result = subprocess.run(
        ["python", full_path],
        text=True,
        capture_output=True
    )
    if result.stdout: print(result.stdout)
    if result.stderr: print(result.stderr)
    return result.returncode == 0


# ----------------------------
# PIPELINE
# ----------------------------
def run_pipeline():
    steps = [
        "getData/phivolcs.py",
        "extracter.py"
    ]
    print(f"🚀 Pipeline starting at {datetime.now().strftime('%H:%M:%S')}")
    for step in steps:
        if not run_step(step):
            print(f"❌ Pipeline failed at: {step}")
            update_status(False)
            broadcast({"event": "status", "API_ONLINE": False})
            return False

    print("✅ Pipeline success")
    update_status(True)

    # Push fresh data to all browsers instantly
    fresh = load_data()
    broadcast({"event": "data", "API_ONLINE": True, "data": fresh})
    return True


# ----------------------------
# BACKGROUND LOOP
# Run pipeline as fast as possible (no artificial wait)
# Add a minimum 5s gap to avoid hammering APIs on errors
# ----------------------------
def scheduler_loop():
    while True:
        start = time.time()
        try:
            run_pipeline()
        except Exception as e:
            print("PIPELINE ERROR:", e)
            update_status(False)
            broadcast({"event": "status", "API_ONLINE": False})

        elapsed = time.time() - start
        gap = max(5, elapsed)   # at least 5s between runs
        print(f"⏱ Next run in {gap:.1f}s")
        time.sleep(gap)


# ----------------------------
# SCHEDULER GUARD
# ----------------------------
_scheduler_started = False

def start_scheduler_once():
    global _scheduler_started
    if _scheduler_started:
        return
    _scheduler_started = True
    thread = threading.Thread(target=scheduler_loop, daemon=True)
    thread.start()
    print("🟢 Scheduler started")


# ----------------------------
# NO-CACHE HELPER
# ----------------------------
def no_cache(response):
    response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response.headers["Pragma"]        = "no-cache"
    response.headers["Expires"]       = "0"
    return response


# ----------------------------
# ROUTES
# ----------------------------
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/data")
def data():
    response = make_response(jsonify(load_data()))
    return no_cache(response)


@app.route("/fault.json")
def fault_file():
    try:
        with open(os.path.join(BASE_DIR, "templates", "fault.json"), "r", encoding="utf-8") as f:
            content = json.load(f)
    except Exception as e:
        print(f"[fault.json] Error loading: {e}")
        content = {"type": "FeatureCollection", "features": []}
    response = make_response(jsonify(content))
    return no_cache(response)


@app.route("/status.json")
def status_file():
    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as f:
            content = json.load(f)
    except Exception:
        content = {"API_ONLINE": False, "last_update": None}
    response = make_response(jsonify(content))
    return no_cache(response)


# ----------------------------
# SSE STREAM ROUTE
# Browser connects once, server pushes forever
# ----------------------------
@app.route("/stream")
def stream():
    q = queue.Queue(maxsize=10)
    with _clients_lock:
        _clients.append(q)

    def generate():
        # Send current data immediately on connect
        try:
            initial = load_data()
            yield f"data: {json.dumps({'event': 'data', 'API_ONLINE': True, 'data': initial})}\n\n"
        except Exception:
            pass

        # Then stream updates as they arrive
        while True:
            try:
                payload = q.get(timeout=25)   # 25s timeout = keepalive heartbeat
                yield f"data: {payload}\n\n"
            except queue.Empty:
                yield ": heartbeat\n\n"        # keep connection alive

    def cleanup():
        with _clients_lock:
            if q in _clients:
                _clients.remove(q)

    response = Response(
        stream_with_context(generate()),
        mimetype="text/event-stream"
    )
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"   # important for nginx
    return response

@app.route("/asset/<path:filename>")
def serve_asset(filename):
    return send_from_directory(os.path.join(BASE_DIR, "templates", "asset"), filename)
# ----------------------------
# MAIN
# ----------------------------
if __name__ == "__main__":
    start_scheduler_once()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)