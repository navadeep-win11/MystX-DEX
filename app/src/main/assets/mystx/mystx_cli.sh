#!/data/data/com.termux/files/usr/bin/sh
#
# MystX DEX — CLI Control Tool
# Usage: mystx [start|stop|restart|status|help]
#

HOST="127.0.0.1"
PORT="${MYSTX_PORT:-8888}"
MYSTX_DIR="${HOME:-/data/data/com.mystx.dex/files/home}/.mystx"
PID_FILE="$MYSTX_DIR/mystx.pid"
LOG_FILE="$MYSTX_DIR/mystx.log"
URL="http://$HOST:$PORT"

mkdir -p "$MYSTX_DIR"

log_info() { printf "\033[1;36m%s\033[0m\n" "$1"; }
log_success() { printf "\033[1;32m%s\033[0m\n" "$1"; }
log_warn() { printf "\033[1;33m%s\033[0m\n" "$1"; }
log_err() { printf "\033[1;31m%s\033[0m\n" "$1"; }

# Locate mystx_server.py
find_server() {
  if [ -f "$PREFIX/share/mystx/mystx_server.py" ]; then
    echo "$PREFIX/share/mystx/mystx_server.py"
  elif [ -f "$MYSTX_DIR/mystx_server.py" ]; then
    echo "$MYSTX_DIR/mystx_server.py"
  elif [ -f "/data/data/com.mystx.dex/files/usr/share/mystx/mystx_server.py" ]; then
    echo "/data/data/com.mystx.dex/files/usr/share/mystx/mystx_server.py"
  elif [ -f "/data/data/com.termux/files/usr/share/mystx/mystx_server.py" ]; then
    echo "/data/data/com.termux/files/usr/share/mystx/mystx_server.py"
  elif [ -f "$(dirname "$0")/mystx_server.py" ]; then
    echo "$(dirname "$0")/mystx_server.py"
  elif [ -f "/data/data/com.termux/files/home/storage/downloads/termux/app/src/main/assets/mystx/mystx_server.py" ]; then
    echo "/data/data/com.termux/files/home/storage/downloads/termux/app/src/main/assets/mystx/mystx_server.py"
  else
    echo ""
  fi
}

SERVER_SCRIPT=$(find_server)

check_python() {
  if command -v python3 >/dev/null 2>&1; then
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    return 0
  fi
  log_err "[!] Python 3 is required to run MystX DEX Web Server."
  echo "Installing Python 3 via package manager..."

  export SSL_CERT_FILE="${SSL_CERT_FILE:-$PREFIX/etc/tls/cert.pem}"
  export CURL_CA_BUNDLE="${CURL_CA_BUNDLE:-$PREFIX/etc/tls/cert.pem}"
  export APT_CONFIG="${APT_CONFIG:-$PREFIX/etc/apt/apt.conf}"
  export DPKG_ADMINDIR="${DPKG_ADMINDIR:-$PREFIX/var/lib/dpkg}"
  export PYTHONHOME="${PYTHONHOME:-$PREFIX}"

  if command -v pkg >/dev/null 2>&1; then
    pkg install -y python
  elif command -v apt >/dev/null 2>&1; then
    apt update && apt install -y python
  fi
  if command -v python3 >/dev/null 2>&1 || command -v python >/dev/null 2>&1; then
    return 0
  fi
  log_err "[!] Failed to install python3 automatically. Please run: pkg install python"
  return 1
}

get_pid() {
  if [ -f "$PID_FILE" ]; then
    if command -v jq >/dev/null 2>&1; then
      jq -r '.pid // empty' "$PID_FILE" 2>/dev/null
    else
      grep -o '"pid": *[0-9]*' "$PID_FILE" 2>/dev/null | grep -o '[0-9]*'
    fi
  fi
}

is_running() {
  PID=$(get_pid)
  if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
    return 0
  fi
  return 1
}

wait_for_server() {
  TRIES=0
  while [ $TRIES -lt 25 ]; do
    if is_running; then
      if command -v curl >/dev/null 2>&1; then
        if curl -s -m 1 "$URL/api/status" >/dev/null 2>&1; then
          return 0
        fi
      elif python3 -c "import urllib.request; urllib.request.urlopen('$URL/api/status', timeout=1)" >/dev/null 2>&1; then
        return 0
      fi
    fi
    sleep 0.2
    TRIES=$((TRIES + 1))
  done
  return 1
}

launch_gui() {
  log_info "[*] Opening MystX DEX Web GUI..."

  # Attempt 1: termux-am socket server
  if command -v termux-am >/dev/null 2>&1; then
    if termux-am start -n com.mystx.dex/com.termux.app.activities.MystxWebActivity >/dev/null 2>&1; then
      log_success "[✓] MystX DEX Web Activity launched."
      return 0
    fi
    if termux-am start -a android.intent.action.VIEW -d "$URL" >/dev/null 2>&1; then
      log_success "[✓] Browser launched via termux-am."
      return 0
    fi
  fi

  # Attempt 2: am binary wrapper
  if command -v am >/dev/null 2>&1; then
    if am start -n com.mystx.dex/com.termux.app.activities.MystxWebActivity >/dev/null 2>&1; then
      log_success "[✓] MystX DEX Web Activity launched."
      return 0
    fi
    if am start -a android.intent.action.VIEW -d "$URL" >/dev/null 2>&1; then
      log_success "[✓] Browser launched via am."
      return 0
    fi
  fi

  # Attempt 3: termux-open-url if available
  if command -v termux-open-url >/dev/null 2>&1; then
    if termux-open-url "$URL" >/dev/null 2>&1; then
      return 0
    fi
  fi

  # Attempt 4: termux-open if available
  if command -v termux-open >/dev/null 2>&1; then
    if termux-open "$URL" >/dev/null 2>&1; then
      return 0
    fi
  fi

  log_success "[✓] Access Web GUI at: $URL"
}

cmd_start() {
  if is_running; then
    PID=$(get_pid)
    log_warn "[!] MystX DEX Web server is already running (PID: $PID)"
    printf "    URL: \033[1;36m%s\033[0m\n" "$URL"
    return 0
  fi

  check_python || return 1

  if [ -z "$SERVER_SCRIPT" ] || [ ! -f "$SERVER_SCRIPT" ]; then
    log_err "[!] MystX DEX Server script not found."
    return 1
  fi

  log_info "[*] Starting MystX DEX Web Server on $HOST:$PORT..."
  nohup python3 "$SERVER_SCRIPT" --host "$HOST" --port "$PORT" > "$LOG_FILE" 2>&1 &

  if wait_for_server; then
    PID=$(get_pid)
    log_success "[✓] MystX DEX Web Server started successfully! (PID: $PID)"
    printf "    URL: \033[1;34m%s\033[0m\n" "$URL"
    return 0
  else
    log_err "[!] Failed to verify server start. Check logs at: $LOG_FILE"
    return 1
  fi
}

cmd_stop() {
  if ! is_running; then
    echo "MystX DEX Web server is not running."
    rm -f "$PID_FILE"
    return 0
  fi

  PID=$(get_pid)
  echo "[*] Stopping MystX DEX Web Server (PID: $PID)..."
  kill -15 "$PID" 2>/dev/null
  sleep 0.5
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null
  fi
  rm -f "$PID_FILE"
  log_success "[✓] Server stopped."
}

cmd_status() {
  if is_running; then
    PID=$(get_pid)
    log_success "● MystX DEX Web Server: RUNNING"
    echo "  PID:     $PID"
    echo "  Local:   $URL"
    echo "  Log:     $LOG_FILE"
  else
    log_err "○ MystX DEX Web Server: STOPPED"
    echo "  Start with: mystx start"
  fi
}

case "$1" in
  start)
    cmd_start
    ;;
  stop)
    cmd_stop
    ;;
  restart)
    cmd_stop
    sleep 0.5
    cmd_start
    ;;
  status)
    cmd_status
    ;;
  help|--help|-h)
    log_info "MystX DEX — Terminal & Web GUI Controller"
    echo ""
    echo "Usage:"
    echo "  mystx          Start the server and launch the Web GUI"
    echo "  mystx start    Start the local Web GUI server in background"
    echo "  mystx stop     Stop the Web GUI server cleanly"
    echo "  mystx restart  Restart the Web GUI server"
    echo "  mystx status   Show running status and local access URL"
    echo "  mystx help     Display this help manual"
    echo ""
    ;;
  "")
    # Default behavior for "mystx"
    if ! is_running; then
      cmd_start
    else
      log_success "[✓] MystX DEX Web Server is already running."
    fi
    launch_gui
    ;;
  *)
    echo "Unknown command: $1"
    echo "Run 'mystx help' for usage instructions."
    exit 1
    ;;
esac
