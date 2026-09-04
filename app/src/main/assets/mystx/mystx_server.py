#!/usr/bin/env python3
"""
MystX DEX — Local-First Web GUI Server & PTY WebSocket Engine
Part of MystX DEX Android Application
"""

import os
import sys
import pty
import tty
import termios
import fcntl
import struct
import select
import socket
import socketserver
import threading
import time
import json
import base64
import hashlib
import mimetypes
import argparse
import signal
from urllib.parse import urlparse, parse_qs, unquote

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8888
SERVER_VERSION = "0.118.0"
WS_MAGIC = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

START_TIME = time.time()
ACTIVE_SESSIONS = {}
SESSION_LOCK = threading.Lock()
SHUTDOWN_EVENT = threading.Event()


class TerminalSession:
    def __init__(self, session_id, command=None, env=None, cwd=None, cols=80, rows=24):
        self.session_id = session_id
        self.cols = cols
        self.rows = rows
        self.created_at = time.time()
        self.closed = False
        self.master_fd, self.slave_fd = pty.openpty()

        # Set initial window size
        self.set_size(cols, rows)

        # Environment setup
        self.env = os.environ.copy()
        if env:
            self.env.update(env)
        self.env["TERM"] = "xterm-256color"
        self.env["COLORTERM"] = "truecolor"
        self.env["MYSTX_DEX"] = "1"
        self.env["MYSTX_VERSION"] = SERVER_VERSION

        # Default shell detection
        if not command:
            termux_bash = "/data/data/com.termux/files/usr/bin/bash"
            termux_sh = "/data/data/com.termux/files/usr/bin/sh"
            if os.path.exists(termux_bash):
                shell = termux_bash
            elif os.path.exists(termux_sh):
                shell = termux_sh
            else:
                shell = os.environ.get("SHELL", "/system/bin/sh")
            command = [shell]

        self.cwd = cwd or os.environ.get("HOME", "/data/data/com.termux/files/home")
        if not os.path.exists(self.cwd):
            self.cwd = os.getcwd()

        # Fork child process
        self.pid = os.fork()
        if self.pid == 0:
            # Child process
            os.close(self.master_fd)
            os.setsid()
            # Set controlling terminal
            try:
                fcntl.ioctl(self.slave_fd, termios.TIOCSCTTY, 0)
            except Exception:
                pass

            os.dup2(self.slave_fd, 0)
            os.dup2(self.slave_fd, 1)
            os.dup2(self.slave_fd, 2)
            if self.slave_fd > 2:
                os.close(self.slave_fd)

            try:
                os.chdir(self.cwd)
            except Exception:
                pass

            for k, v in self.env.items():
                os.environ[k] = v

            try:
                os.execvpe(command[0], command, self.env)
            except Exception as e:
                sys.stderr.write(f"MystX: Failed to exec {command[0]}: {e}\n")
                sys.exit(1)
        else:
            # Parent process
            os.close(self.slave_fd)
            # Set non-blocking on master_fd
            flags = fcntl.fcntl(self.master_fd, fcntl.F_GETFL)
            fcntl.fcntl(self.master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

    def set_size(self, cols, rows):
        self.cols = max(1, cols)
        self.rows = max(1, rows)
        try:
            winsize = struct.pack("HHHH", self.rows, self.cols, 0, 0)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    def write(self, data):
        if self.closed:
            return
        if isinstance(data, str):
            data = data.encode("utf-8", errors="ignore")
        try:
            os.write(self.master_fd, data)
        except (OSError, IOError):
            self.close()

    def read(self, size=4096):
        if self.closed:
            return b""
        try:
            return os.read(self.master_fd, size)
        except (BlockingIOError, InterruptedError):
            return b""
        except (OSError, IOError):
            self.close()
            return b""

    def is_alive(self):
        if self.closed:
            return False
        try:
            pid, status = os.waitpid(self.pid, os.WNOHANG)
            if pid == self.pid:
                self.closed = True
                return False
            return True
        except ChildProcessError:
            self.closed = True
            return False

    def close(self):
        if not self.closed:
            self.closed = True
            try:
                os.close(self.master_fd)
            except Exception:
                pass
            try:
                os.kill(self.pid, signal.SIGTERM)
            except Exception:
                pass


def get_or_create_session(session_id=None, cols=80, rows=24):
    with SESSION_LOCK:
        if session_id and session_id in ACTIVE_SESSIONS:
            sess = ACTIVE_SESSIONS[session_id]
            if sess.is_alive():
                sess.set_size(cols, rows)
                return sess
            else:
                del ACTIVE_SESSIONS[session_id]

        new_id = session_id or f"sess-{int(time.time()*1000)}"
        sess = TerminalSession(new_id, cols=cols, rows=rows)
        ACTIVE_SESSIONS[new_id] = sess
        return sess


def kill_session(session_id):
    with SESSION_LOCK:
        if session_id in ACTIVE_SESSIONS:
            ACTIVE_SESSIONS[session_id].close()
            del ACTIVE_SESSIONS[session_id]
            return True
        return False


def build_ws_frame(payload, opcode=0x1):
    """Build unmasked WebSocket frame to send to client (Server-to-Client frames must be unmasked)."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    length = len(payload)
    frame = bytearray()
    frame.append(0x80 | (opcode & 0x0F))  # FIN bit + opcode

    if length < 126:
        frame.append(length)
    elif length < 65536:
        frame.append(126)
        frame.extend(struct.pack("!H", length))
    else:
        frame.append(127)
        frame.extend(struct.pack("!Q", length))

    frame.extend(payload)
    return bytes(frame)


def parse_ws_frame(reader):
    """Read and decode a masked WebSocket frame sent by client."""
    header = reader.read(2)
    if not header or len(header) < 2:
        return None, None
    b1, b2 = header[0], header[1]
    fin = (b1 & 0x80) != 0
    opcode = b1 & 0x0F
    is_masked = (b2 & 0x80) != 0
    payload_len = b2 & 0x7F

    if payload_len == 126:
        ext = reader.read(2)
        if len(ext) < 2:
            return None, None
        payload_len = struct.unpack("!H", ext)[0]
    elif payload_len == 127:
        ext = reader.read(8)
        if len(ext) < 8:
            return None, None
        payload_len = struct.unpack("!Q", ext)[0]

    mask_key = None
    if is_masked:
        mask_key = reader.read(4)
        if len(mask_key) < 4:
            return None, None

    payload = bytearray()
    remaining = payload_len
    while remaining > 0:
        chunk = reader.read(min(remaining, 8192))
        if not chunk:
            return None, None
        payload.extend(chunk)
        remaining -= len(chunk)

    if is_masked and mask_key:
        for i in range(len(payload)):
            payload[i] ^= mask_key[i % 4]

    return opcode, bytes(payload)


class MystxRequestHandler(socketserver.BaseRequestHandler):
    def handle(self):
        self.rfile = self.request.makefile("rb", -1)
        self.wfile = self.request.makefile("wb", 0)

        # Read HTTP request line
        req_line = self.rfile.readline().decode("utf-8", errors="ignore").strip()
        if not req_line:
            return

        parts = req_line.split()
        if len(parts) < 2:
            return
        method, full_path = parts[0], parts[1]

        # Read headers
        headers = {}
        while True:
            line = self.rfile.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                break
            if ":" in line:
                k, v = line.split(":", 1)
                headers[k.strip().lower()] = v.strip()

        parsed_url = urlparse(full_path)
        path = parsed_url.path
        query = parse_qs(parsed_url.query)

        # Check for WebSocket Upgrade
        if headers.get("upgrade", "").lower() == "websocket":
            self.handle_websocket(path, query, headers)
            return

        # Handle HTTP Routes
        if method == "GET":
            self.handle_get(path, query)
        elif method == "POST":
            content_len = int(headers.get("content-length", 0))
            post_body = self.rfile.read(content_len) if content_len > 0 else b"{}"
            self.handle_post(path, query, post_body)
        else:
            self.send_response(405, "Method Not Allowed", "text/plain", b"Method Not Allowed")

    def handle_websocket(self, path, query, headers):
        key = headers.get("sec-websocket-key", "")
        if not key:
            self.send_response(400, "Bad Request", "text/plain", b"Missing Sec-WebSocket-Key")
            return

        # Perform handshake
        accept_val = base64.b64encode(hashlib.sha1((key + WS_MAGIC).encode()).digest()).decode()
        response = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_val}\r\n"
            "\r\n"
        )
        self.wfile.write(response.encode())
        self.wfile.flush()

        # Session selection
        session_id = query.get("session", [None])[0]
        cols = int(query.get("cols", [80])[0])
        rows = int(query.get("rows", [24])[0])

        terminal_session = get_or_create_session(session_id, cols=cols, rows=rows)

        # Notify frontend of session info
        init_msg = json.dumps({
            "type": "session_init",
            "session_id": terminal_session.session_id,
            "pid": terminal_session.pid,
            "cols": terminal_session.cols,
            "rows": terminal_session.rows
        })
        self.wfile.write(build_ws_frame(init_msg))

        # Thread to stream PTY output to WebSocket
        running = threading.Event()
        running.set()

        def pty_reader():
            while running.is_set() and not SHUTDOWN_EVENT.is_set():
                r, _, _ = select.select([terminal_session.master_fd], [], [], 0.05)
                if r:
                    data = terminal_session.read(4096)
                    if data:
                        try:
                            self.wfile.write(build_ws_frame(data, opcode=0x2))
                        except Exception:
                            break
                    else:
                        # PTY closed
                        break
                if not terminal_session.is_alive():
                    try:
                        self.wfile.write(build_ws_frame(json.dumps({"type": "exit", "code": 0})))
                    except Exception:
                        pass
                    break
            running.clear()

        reader_thread = threading.Thread(target=pty_reader, daemon=True)
        reader_thread.start()

        # Read loop from client WebSocket
        try:
            while running.is_set() and not SHUTDOWN_EVENT.is_set():
                opcode, payload = parse_ws_frame(self.rfile)
                if opcode is None or opcode == 0x8:  # Close
                    break
                elif opcode == 0x9:  # Ping
                    self.wfile.write(build_ws_frame(payload, opcode=0xA))
                elif opcode == 0x1 or opcode == 0x2:  # Text or Binary
                    # Check if JSON command (e.g. resize, ping)
                    handled = False
                    if opcode == 0x1:
                        try:
                            msg = json.loads(payload.decode("utf-8"))
                            mtype = msg.get("type")
                            if mtype == "resize":
                                terminal_session.set_size(msg.get("cols", 80), msg.get("rows", 24))
                                handled = True
                            elif mtype == "ping":
                                self.wfile.write(build_ws_frame(json.dumps({"type": "pong"})))
                                handled = True
                            elif mtype == "input":
                                terminal_session.write(msg.get("data", ""))
                                handled = True
                        except Exception:
                            pass
                    if not handled:
                        terminal_session.write(payload)
        except Exception:
            pass
        finally:
            running.clear()
            reader_thread.join(timeout=0.5)

    def handle_get(self, path, query):
        if path == "/api/status":
            uptime = int(time.time() - START_TIME)
            with SESSION_LOCK:
                sessions_info = [
                    {
                        "id": sid,
                        "pid": s.pid,
                        "created_at": s.created_at,
                        "cols": s.cols,
                        "rows": s.rows,
                        "alive": s.is_alive()
                    }
                    for sid, s in ACTIVE_SESSIONS.items()
                ]

            status_data = {
                "product": "MystX DEX",
                "version": SERVER_VERSION,
                "status": "online",
                "uptime_seconds": uptime,
                "pid": os.getpid(),
                "active_sessions": len(sessions_info),
                "sessions": sessions_info,
                "host": DEFAULT_HOST,
                "port": self.server.server_address[1],
                "system": {
                    "platform": sys.platform,
                    "python": sys.version.split()[0],
                    "home": os.environ.get("HOME", "")
                }
            }
            self.send_json(status_data)
            return

        elif path == "/api/sessions":
            with SESSION_LOCK:
                sessions_info = [
                    {
                        "id": sid,
                        "pid": s.pid,
                        "created_at": s.created_at,
                        "cols": s.cols,
                        "rows": s.rows,
                        "alive": s.is_alive()
                    }
                    for sid, s in ACTIVE_SESSIONS.items()
                ]
            self.send_json({"sessions": sessions_info})
            return

        elif path == "/api/files/list":
            req_path = query.get("path", [os.environ.get("HOME", "/data/data/com.termux/files/home")])[0]
            req_path = os.path.realpath(req_path)
            # Security verification
            allowed_roots = [
                os.path.realpath(os.environ.get("HOME", "/data/data/com.termux/files/home")),
                "/sdcard",
                "/storage/emulated/0",
                "/data/data/com.termux/files/usr"
            ]
            is_allowed = any(req_path.startswith(root) for root in allowed_roots) or os.access(req_path, os.R_OK)

            if not os.path.exists(req_path) or not is_allowed:
                self.send_json({"error": "Path not accessible"}, status=403)
                return

            try:
                entries = []
                for entry in sorted(os.scandir(req_path), key=lambda e: (not e.is_dir(), e.name.lower())):
                    stat = entry.stat()
                    entries.append({
                        "name": entry.name,
                        "is_dir": entry.is_dir(),
                        "size": stat.st_size if not entry.is_dir() else 0,
                        "mtime": stat.st_mtime,
                        "path": entry.path
                    })
                self.send_json({"current_path": req_path, "files": entries})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        elif path == "/api/files/read":
            req_path = query.get("path", [""])[0]
            req_path = os.path.realpath(req_path)
            if not os.path.isfile(req_path):
                self.send_json({"error": "File not found"}, status=404)
                return
            if os.path.getsize(req_path) > 2 * 1024 * 1024:
                self.send_json({"error": "File too large (> 2MB)"}, status=400)
                return
            try:
                with open(req_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()
                self.send_json({"path": req_path, "content": content})
            except Exception as e:
                self.send_json({"error": str(e)}, status=500)
            return

        elif path == "/api/ai/models":
            # Future AI Architecture Provider registry
            ai_data = {
                "architecture": "MystX DEX Extensible AI Agent System",
                "ready": True,
                "providers": [
                    {
                        "id": "local_ollama",
                        "name": "Local Ollama / Llama.cpp",
                        "endpoint": "http://127.0.0.1:11434",
                        "status": "configurable"
                    },
                    {
                        "id": "gemini",
                        "name": "Google Gemini API",
                        "endpoint": "https://generativelanguage.googleapis.com",
                        "status": "ready_for_key"
                    },
                    {
                        "id": "openai_compatible",
                        "name": "OpenAI Compatible / Custom",
                        "endpoint": "http://127.0.0.1:8000/v1",
                        "status": "configurable"
                    },
                    {
                        "id": "anthropic",
                        "name": "Anthropic Claude",
                        "endpoint": "https://api.anthropic.com",
                        "status": "ready_for_key"
                    }
                ],
                "active_model": "local_ollama",
                "tools_available": ["shell_exec", "file_read", "file_write", "git_status"]
            }
            self.send_json(ai_data)
            return

        # Serve static files from web assets directory
        self.serve_static(path)

    def handle_post(self, path, query, body):
        try:
            data = json.loads(body.decode("utf-8")) if body else {}
        except Exception:
            data = {}

        if path == "/api/sessions/new":
            cols = data.get("cols", 80)
            rows = data.get("rows", 24)
            session_id = data.get("session_id")
            sess = get_or_create_session(session_id, cols=cols, rows=rows)
            self.send_json({
                "status": "created",
                "session_id": sess.session_id,
                "pid": sess.pid
            })
            return

        elif path == "/api/sessions/kill":
            session_id = data.get("session_id")
            if session_id and kill_session(session_id):
                self.send_json({"status": "killed", "session_id": session_id})
            else:
                self.send_json({"error": "Session not found"}, status=404)
            return

        elif path == "/api/ai/chat":
            # Future AI Agent endpoint hook
            prompt = data.get("prompt", "")
            model = data.get("model", "local_ollama")
            # Return structured extensible agent payload
            response = {
                "role": "assistant",
                "content": f"[MystX DEX AI Agent Workspace]\nReceived: {prompt}\n\nAI Agent architecture hook is active and ready for model endpoint connection ({model}). Connect your local model server or set your API key in Settings -> AI to enable autonomous execution.",
                "model": model,
                "tool_calls": []
            }
            self.send_json(response)
            return

        self.send_response(404, "Not Found", "application/json", b'{"error":"Endpoint not found"}')

    def serve_static(self, path):
        web_root = self.server.web_dir
        if path == "/" or not path:
            path = "/index.html"
        safe_path = os.path.normpath(unquote(path)).lstrip("/")
        full_path = os.path.join(web_root, safe_path)

        if not os.path.exists(full_path) or os.path.isdir(full_path):
            full_path = os.path.join(web_root, "index.html")

        content_type, _ = mimetypes.guess_type(full_path)
        if not content_type:
            content_type = "application/octet-stream"

        try:
            with open(full_path, "rb") as f:
                content = f.read()
            self.send_response(200, "OK", content_type, content)
        except Exception as e:
            self.send_response(500, "Internal Server Error", "text/plain", str(e).encode())

    def send_response(self, status_code, status_text, content_type, body):
        header = (
            f"HTTP/1.1 {status_code} {status_text}\r\n"
            f"Content-Type: {content_type}\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Access-Control-Allow-Origin: *\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        )
        try:
            self.wfile.write(header.encode() + body)
            self.wfile.flush()
        except Exception:
            pass

    def send_json(self, data, status=200):
        body = json.dumps(data, indent=2).encode("utf-8")
        status_text = "OK" if status == 200 else "Error"
        self.send_response(status, status_text, "application/json; charset=utf-8", body)


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, server_address, RequestHandlerClass, web_dir):
        self.web_dir = web_dir
        super().__init__(server_address, RequestHandlerClass)


def write_pid_file(port):
    home = os.environ.get("HOME", "/data/data/com.termux/files/home")
    mystx_dir = os.path.join(home, ".mystx")
    os.makedirs(mystx_dir, exist_ok=True)
    pid_file = os.path.join(mystx_dir, "mystx.pid")
    info = {
        "pid": os.getpid(),
        "port": port,
        "host": DEFAULT_HOST,
        "started_at": START_TIME
    }
    with open(pid_file, "w") as f:
        json.dump(info, f)


def remove_pid_file():
    home = os.environ.get("HOME", "/data/data/com.termux/files/home")
    pid_file = os.path.join(home, ".mystx", "mystx.pid")
    if os.path.exists(pid_file):
        try:
            os.remove(pid_file)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(description="MystX DEX Web Server")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to bind (default: 8888)")
    parser.add_argument("--dir", default=None, help="Directory containing web assets")
    args = parser.parse_args()

    # Determine web assets directory
    script_dir = os.path.dirname(os.path.realpath(__file__))
    web_dir = args.dir
    if not web_dir:
        candidates = [
            os.path.join(script_dir, "web"),
            os.path.join(os.environ.get("HOME", ""), ".mystx", "web"),
            "/data/data/com.termux/files/usr/share/mystx/web"
        ]
        for c in candidates:
            if os.path.exists(c) and os.path.isdir(c):
                web_dir = c
                break
        if not web_dir:
            web_dir = os.path.join(script_dir, "web")

    def sig_handler(signum, frame):
        SHUTDOWN_EVENT.set()
        remove_pid_file()
        with SESSION_LOCK:
            for s in list(ACTIVE_SESSIONS.values()):
                s.close()
        sys.exit(0)

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    server = ThreadedTCPServer((args.host, args.port), MystxRequestHandler, web_dir)
    write_pid_file(args.port)
    print(f"[*] MystX DEX Web Server running at http://{args.host}:{args.port}")
    print(f"[*] Serving UI from {web_dir}")
    print(f"[*] PID: {os.getpid()}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        remove_pid_file()


if __name__ == "__main__":
    main()
