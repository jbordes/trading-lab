"""Connection admission and bounded network lifetime for local HTTP services."""

from __future__ import annotations

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class BoundedHTTPServer(ThreadingHTTPServer):
    """Limit workers before spawning; interrupt stalled and trickling sockets."""

    daemon_threads = True
    request_queue_size = 8

    def __init__(
        self,
        address: tuple[str, int],
        handler: type[BaseHTTPRequestHandler],
        *,
        max_connections: int,
        request_timeout: float,
    ) -> None:
        self._max_connections = max_connections
        self._request_timeout = request_timeout
        self._active: set[socket.socket] = set()
        self._connections_lock = threading.Lock()
        self._closing = False
        self._rejected = 0
        self._expired = 0
        super().__init__(address, handler)

    def connection_state(self) -> dict[str, int | float]:
        with self._connections_lock:
            return {
                "active_connections": len(self._active),
                "max_connections": self._max_connections,
                "rejected_connections": self._rejected,
                "expired_connections": self._expired,
                "request_timeout_seconds": self._request_timeout,
            }

    def process_request(self, request: socket.socket, client_address: tuple[str, int]) -> None:
        with self._connections_lock:
            admitted = not self._closing and len(self._active) < self._max_connections
            if admitted:
                self._active.add(request)
            else:
                self._rejected += 1
        if not admitted:
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except RuntimeError:
            # Thread creation failed; do not permanently consume an admission slot.
            with self._connections_lock:
                self._active.discard(request)
            self.shutdown_request(request)
            raise

    def process_request_thread(
        self, request: socket.socket, client_address: tuple[str, int]
    ) -> None:
        deadline = threading.Timer(self._request_timeout, self._expire, args=(request,))
        deadline.daemon = True
        try:
            request.settimeout(self._request_timeout)
            deadline.start()
            super().process_request_thread(request, client_address)
        finally:
            deadline.cancel()
            if deadline.ident is not None:
                deadline.join()
            self.shutdown_request(request)
            with self._connections_lock:
                self._active.discard(request)

    def _expire(self, request: socket.socket) -> None:
        with self._connections_lock:
            if request not in self._active:
                return
            self._expired += 1
        self._interrupt(request)

    @staticmethod
    def _interrupt(request: socket.socket) -> None:
        try:
            request.shutdown(socket.SHUT_RDWR)
        except OSError:
            # Normal race with a completed request or a peer that already closed.
            pass

    def server_close(self) -> None:
        with self._connections_lock:
            self._closing = True
            active = tuple(self._active)
        for request in active:
            self._interrupt(request)
        super().server_close()


# Compatibility name for the receiver while the bounded server is shared by
# other local HTTP services.
BoundedTelemetryServer = BoundedHTTPServer
