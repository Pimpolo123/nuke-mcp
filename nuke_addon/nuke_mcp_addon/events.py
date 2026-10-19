"""Event push to every connected client (node created/deleted, knob changed, ...)."""

import json
import threading

_clients = set()
_lock = threading.Lock()


def add_client(sock):
    with _lock:
        _clients.add(sock)


def remove_client(sock):
    with _lock:
        _clients.discard(sock)


def push(event_type, data):
    with _lock:
        clients = list(_clients)
    if not clients:
        return
    msg = (json.dumps({"type": "event", "event_type": event_type, "data": data}) + "\n")
    payload = msg.encode("utf-8")
    for client in clients:
        try:
            client.sendall(payload)
        except OSError:
            remove_client(client)
