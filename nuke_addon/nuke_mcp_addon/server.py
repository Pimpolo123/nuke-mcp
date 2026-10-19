"""TCP socket server that runs inside Nuke.

Protocol: newline-delimited JSON. On connect the addon sends a handshake; each
request is {"type": <command>, "params": {...}} and gets exactly one response.
Event messages ({"type": "event", ...}) may be interleaved.

Commands are executed on Nuke's main thread (the only thread where the Nuke
API is safe) through dispatch.run_command, which never raises.
"""

import json
import logging
import os
import queue
import socket
import sys
import threading

from . import console, events, registry
from .constants import ADDON_VERSION, DEFAULT_PORT, ENV_PORT, HOST, PORT_RANGE
from .dispatch import COMMANDS, run_command
from .util import get_nuke

log = logging.getLogger("NukeMCP")

# Headless (nuke -t) servers pump commands from this queue on the main thread.
# Background workers (async renders) use call_main() to get there too.
_MAIN_QUEUE = None


def call_main(func, *args):
    """Run func on Nuke's main thread from any thread and return its result."""
    nuke = get_nuke()
    if getattr(nuke, "GUI", False):
        return nuke.executeInMainThreadWithResult(func, args=args)
    if _MAIN_QUEUE is not None:
        result_q = queue.Queue()
        _MAIN_QUEUE.put((func, args, result_q))
        return result_q.get()
    return func(*args)


_script_callbacks_installed = globals().get("_script_callbacks_installed", False)


def _refresh_script_name():
    try:
        name = get_nuke().root().name()
    except Exception:
        return
    registry.update(script="" if name == "Root" else name)


def _script_closed():
    registry.update(script="")


def _install_script_callbacks():
    """Keep the instance registry's script name current without any command:
    the addon starts from menu.py, before the script is loaded."""
    global _script_callbacks_installed
    if _script_callbacks_installed:
        return
    nuke = get_nuke()
    for adder, fn in (("addOnScriptLoad", _refresh_script_name),
                      ("addOnScriptSave", _refresh_script_name),
                      ("addOnScriptClose", _script_closed)):
        add = getattr(nuke, adder, None)
        if add is not None:
            try:
                add(fn)
            except Exception:
                pass
    _script_callbacks_installed = True


def handshake_data(port):
    nuke = get_nuke()
    if nuke.env.get("studio"):
        variant = "NukeStudio"
    elif nuke.env.get("nukex"):
        variant = "NukeX"
    else:
        variant = "Nuke"
    try:
        script = nuke.root().name()
    except Exception:
        script = ""
    if script == "Root":  # unsaved script
        script = ""
    return {
        "type": "handshake",
        "nuke_version": nuke.NUKE_VERSION_STRING,
        "variant": variant,
        "pid": os.getpid(),
        "port": port,
        "script": script,
        "gui": bool(getattr(nuke, "GUI", False)),
        "addon_version": ADDON_VERSION,
        "python": sys.version.split()[0],
        "commands": sorted(COMMANDS),
    }


class NukeMCPServer:
    """Listens on the first free port in [port, port + PORT_RANGE)."""

    def __init__(self, port=DEFAULT_PORT, log_callback=None):
        self.requested_port = port
        self.port = port
        self._sock = None
        self._running = False
        self._thread = None
        self._main_queue = None  # headless: commands are pumped by serve_forever
        self._log_callbacks = [log_callback] if log_callback else []

    # -- lifecycle ---------------------------------------------------------

    def start(self):
        if self._running:
            return
        self._bind()
        self._running = True
        os.environ[ENV_PORT] = str(self.port)
        console.install()
        try:
            # start() is called on the main thread (menu.py, the panel button or
            # serve_forever), so the Nuke API can be used directly here.
            hs = handshake_data(self.port)
            registry.start(self.port, hs["nuke_version"], hs["variant"], hs["script"])
        except Exception:
            registry.start(self.port, "", "", "")
        _install_script_callbacks()
        self._thread = threading.Thread(target=self._accept_loop, name="nuke-mcp-accept",
                                        daemon=True)
        self._thread.start()
        self._emit("NukeMCP %s listening on %s:%d" % (ADDON_VERSION, HOST, self.port))

    def stop(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        registry.stop()
        self._emit("NukeMCP stopped")

    @property
    def running(self):
        return self._running

    def serve_forever(self):
        """Headless mode (nuke -t): pump commands on the calling thread."""
        global _MAIN_QUEUE
        self._main_queue = queue.Queue()
        _MAIN_QUEUE = self._main_queue
        self.start()
        try:
            while self._running:
                try:
                    func, args, result_q = self._main_queue.get(timeout=0.1)
                except queue.Empty:
                    continue
                try:
                    result_q.put(func(*args))
                except Exception as e:  # run_command never raises; keep the pump alive anyway
                    result_q.put({"status": "error", "error": str(e)})
        except KeyboardInterrupt:
            pass
        finally:
            self._main_queue = None
            _MAIN_QUEUE = None
            self.stop()

    # -- internals ---------------------------------------------------------

    def _bind(self):
        last_error = None
        for port in range(self.requested_port, self.requested_port + PORT_RANGE):
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                # Windows: SO_REUSEADDR lets a second Nuke bind a port that is
                # already taken, and connections keep landing on the first one.
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((HOST, port))
            except OSError as e:
                last_error = e
                sock.close()
                continue
            sock.settimeout(1.0)
            sock.listen(8)
            self.port = port
            self._sock = sock
            return
        raise OSError("No free port in %d-%d: %s" % (
            self.requested_port, self.requested_port + PORT_RANGE - 1, last_error))

    def _accept_loop(self):
        while self._running:
            try:
                client, addr = self._sock.accept()
            except socket.timeout:
                continue
            except (OSError, AttributeError):
                break
            self._emit("Client connected from %s:%d" % addr)
            # One thread per client: an in-Nuke assistant and a terminal session
            # can be attached at the same time.
            threading.Thread(target=self._serve_client, args=(client,), daemon=True).start()

    def _call_main(self, func, *args):
        return call_main(func, *args)

    def _serve_client(self, client):
        client.settimeout(None)
        events.add_client(client)
        try:
            hs = self._call_main(handshake_data, self.port)
            if not isinstance(hs, dict):
                return
            self._send(client, hs)
            self._client_loop(client)
        finally:
            events.remove_client(client)
            try:
                client.close()
            except OSError:
                pass
            self._emit("Client disconnected")

    def _client_loop(self, client):
        buffer = b""
        while self._running:
            try:
                chunk = client.recv(1024 * 1024)
            except OSError:
                break
            if not chunk:
                break
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                if not line.strip():
                    continue
                try:
                    request = json.loads(line.decode("utf-8"))
                except ValueError as e:
                    self._send(client, {"status": "error", "error": "Invalid JSON: %s" % e})
                    continue
                name = request.get("type", "")
                self._emit("<- %s" % name)
                response = self._call_main(run_command, name, request.get("params") or {})
                if not isinstance(response, dict):
                    response = {"status": "error",
                                "error": "Nuke returned no result for '%s'" % name}
                self._send(client, response)
                self._emit("-> %s %s" % (name, response.get("status", "?")))

    def _send(self, client, data):
        try:
            client.sendall((json.dumps(data) + "\n").encode("utf-8"))
        except OSError:
            pass

    def _emit(self, msg):
        log.info(msg)
        for cb in list(self._log_callbacks):
            try:
                cb(msg)
            except Exception:
                pass

    def add_log_callback(self, cb):
        self._log_callbacks.append(cb)
