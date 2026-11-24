#!/usr/bin/env python3
"""Кадровый учёт — служба персонала (БНТУ).

Десктопная программа: все данные хранятся в базе SQLite рядом с файлом
программы, интерфейс открывается в окне браузера. Работает только на
локальном компьютере (127.0.0.1), никаких зависимостей — нужен лишь Python 3.8+.

Запуск:
    python кадровый_учёт.py              # порт 8417, открыть окно браузера
    python кадровый_учёт.py --port 9000  # другой порт
    python кадровый_учёт.py --no-browser # не открывать браузер автоматически
"""
import argparse
import json
import os
import sqlite3
import sys
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(BASE_DIR, "ui")
DB_PATH = os.path.join(BASE_DIR, "кадровый_учёт.db")

TABLES = {
    "employees": [
        "id TEXT PRIMARY KEY",
        "pos INTEGER",
        "data TEXT NOT NULL",
    ],
    "docs": [
        "id TEXT PRIMARY KEY",
        "pos INTEGER",
        "employeeId TEXT",
        "data TEXT NOT NULL",
    ],
    "incoming": [
        "id TEXT PRIMARY KEY",
        "pos INTEGER",
        "data TEXT NOT NULL",
    ],
    "kv": [
        "key TEXT PRIMARY KEY",
        "value TEXT NOT NULL",
    ],
}
KV_KEYS = ("settings", "templates", "tplSettings")
db_lock = threading.Lock()
_conn = None


def get_conn():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        _conn.execute("PRAGMA journal_mode=WAL")
        for table, cols in TABLES.items():
            _conn.execute(
                "CREATE TABLE IF NOT EXISTS %s (%s)" % (table, ", ".join(cols))
            )
        _conn.commit()
    return _conn


def load_db():
    conn = get_conn()
    data = {"employees": [], "docs": [], "incoming": []}
    with db_lock:
        rows = conn.execute(
            "SELECT data FROM employees ORDER BY pos ASC, rowid ASC"
        ).fetchall()
        for (raw,) in rows:
            data["employees"].append(json.loads(raw))
        rows = conn.execute(
            "SELECT data FROM docs ORDER BY pos ASC, rowid ASC"
        ).fetchall()
        for (raw,) in rows:
            data["docs"].append(json.loads(raw))
        rows = conn.execute(
            "SELECT data FROM incoming ORDER BY pos ASC, rowid ASC"
        ).fetchall()
        for (raw,) in rows:
            data["incoming"].append(json.loads(raw))
        for key in KV_KEYS:
            row = conn.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                data[key] = json.loads(row[0])
    return data


def save_db(data):
    conn = get_conn()
    with db_lock:
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            cur.execute("DELETE FROM employees")
            cur.execute("DELETE FROM docs")
            cur.execute("DELETE FROM incoming")
            for pos, item in enumerate(data.get("employees", [])):
                cur.execute(
                    "INSERT INTO employees (id, pos, data) VALUES (?, ?, ?)",
                    (str(item.get("id", pos)), pos, json.dumps(item, ensure_ascii=False)),
                )
            for pos, item in enumerate(data.get("docs", [])):
                cur.execute(
                    "INSERT INTO docs (id, pos, employeeId, data) VALUES (?, ?, ?, ?)",
                    (
                        str(item.get("id", pos)),
                        pos,
                        str(item.get("employeeId", "")),
                        json.dumps(item, ensure_ascii=False),
                    ),
                )
            for pos, item in enumerate(data.get("incoming", [])):
                cur.execute(
                    "INSERT INTO incoming (id, pos, data) VALUES (?, ?, ?)",
                    (str(item.get("id", pos)), pos, json.dumps(item, ensure_ascii=False)),
                )
            for key in KV_KEYS:
                if key in data:
                    cur.execute(
                        "INSERT INTO kv (key, value) VALUES (?, ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (key, json.dumps(data[key], ensure_ascii=False)),
                    )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def wrap(handler, status, body, ctype="application/json; charset=utf-8"):
    payload = body if isinstance(body, bytes) else body.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=UI_DIR, **kwargs)

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.split("?")[0] == "/api/db":
            try:
                wrap(self, 200, json.dumps(load_db(), ensure_ascii=False))
            except Exception as exc:
                wrap(self, 500, json.dumps({"error": str(exc)}))
            return
        super().do_GET()

    def do_POST(self):
        if self.path.split("?")[0] != "/api/db":
            wrap(self, 404, json.dumps({"error": "not found"}))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(data, dict) or "employees" not in data or "docs" not in data or "incoming" not in data:
                raise ValueError("неверные данные")
            save_db(data)
            wrap(self, 200, json.dumps({"ok": True}))
        except Exception as exc:
            wrap(self, 500, json.dumps({"error": str(exc)}))


def main():
    parser = argparse.ArgumentParser(description="Кадровый учёт (SQLite)")
    parser.add_argument("--port", type=int, default=8417)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    host = "127.0.0.1"
    get_conn()
    server = ThreadingHTTPServer((host, args.port), Handler)
    url = "http://%s:%d/" % (host, args.port)
    print("=" * 46)
    print("  Кадровый учёт — служба персонала")
    print("  Данные: %s" % DB_PATH)
    print("  Адрес:  %s" % url)
    print("  Интерфейс откроется в окне браузера.")
    print("  Не закрывайте это окно — оно держит базу.")
    print("  Для выхода нажмите Ctrl+C.")
    print("=" * 46)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nПрограмма закрыта.")
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
