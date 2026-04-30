"""
TCP-сервер удалённого управления тестовым клиентом ПЭМИН.

Детектор (сервер) → Тестовый клиент (клиент):
  {"cmd": "test_start"}  — включить тестовый сигнал
  {"cmd": "test_stop"}   — выключить тестовый сигнал
  {"cmd": "ping"}        — проверка связи

Клиент → Детектор:
  {"status": "ack", "active": true/false}
"""

from __future__ import annotations

import json
import socket
import threading
from typing import Callable

PORT_DEFAULT = 62000


class RemoteControlServer:
    """
    Запускается при старте детектора, принимает подключения тестовых клиентов.
    Потокобезопасен: все методы можно вызывать из рабочего потока workflow.
    """

    def __init__(self) -> None:
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._server_sock: socket.socket | None = None
        self._running = False
        self._port: int = PORT_DEFAULT
        self.on_client_count_changed: Callable[[int], None] = lambda n: None

    # ── Публичный интерфейс ────────────────────────────────────────────

    @property
    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def local_address(self) -> str:
        """Возвращает 'IP:порт' для отображения в UI."""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
        except OSError:
            ip = "127.0.0.1"
        return f"{ip}:{self._port}"

    def start(self, port: int = PORT_DEFAULT) -> None:
        if self._running:
            return
        self._port = port
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind(("0.0.0.0", port))
        self._server_sock.listen(8)
        self._server_sock.settimeout(1.0)
        self._running = True
        threading.Thread(
            target=self._accept_loop, daemon=True, name="rc-server-accept"
        ).start()

    def stop(self) -> None:
        self._running = False
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass
            self._server_sock = None
        with self._lock:
            for conn in self._clients:
                try:
                    conn.close()
                except OSError:
                    pass
            self._clients.clear()

    def send_test_start(self) -> int:
        return self._broadcast({"cmd": "test_start"})

    def send_test_stop(self) -> int:
        return self._broadcast({"cmd": "test_stop"})

    # ── Внутренняя реализация ──────────────────────────────────────────

    def _broadcast(self, msg: dict) -> int:
        data = (json.dumps(msg) + "\n").encode()
        reached = 0
        with self._lock:
            dead: list[socket.socket] = []
            for conn in self._clients:
                try:
                    conn.sendall(data)
                    reached += 1
                except OSError:
                    dead.append(conn)
            for c in dead:
                self._clients.remove(c)
        if dead:
            self.on_client_count_changed(len(self._clients))
        return reached

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._server_sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            conn.settimeout(None)
            with self._lock:
                self._clients.append(conn)
            self.on_client_count_changed(len(self._clients))
            threading.Thread(
                target=self._watch_client, args=(conn,), daemon=True
            ).start()

    def _watch_client(self, conn: socket.socket) -> None:
        try:
            while self._running:
                data = conn.recv(256)
                if not data:
                    break
        except OSError:
            pass
        finally:
            with self._lock:
                if conn in self._clients:
                    self._clients.remove(conn)
            self.on_client_count_changed(len(self._clients))
            try:
                conn.close()
            except OSError:
                pass
