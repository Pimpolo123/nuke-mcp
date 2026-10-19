"""Socket connection to the Nuke addon."""

import json
import logging
import os
import queue
import socket
import tempfile
import threading
import time

log = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
PORT_RANGE = 10  # the addon takes the first free port in 54321-54330
# A Nuke session exports the port its addon bound as NUKE_MCP_PORT, so an MCP
# server launched from inside that Nuke (e.g. by an in-Nuke assistant panel)
# talks to that same session by default.
DEFAULT_PORT = int(os.environ.get("NUKE_MCP_PORT", "54321"))
BASE_PORT = 54321
RECV_BUFFER = 1024 * 1024  # 1MB
REGISTRY_STALE_SECONDS = 35  # the addon heartbeats every 10 s


class NukeConnectionError(Exception):
    """Failed to connect or communicate with the Nuke addon."""


def registry_instances() -> dict[int, dict]:
    """Sessions announced in %TEMP%/nuke_mcp/instances by addon >= 0.2.

    Readable without a socket, so a session busy rendering is still listed.
    Entries whose heartbeat is older than REGISTRY_STALE_SECONDS are ignored.
    """
    folder = os.path.join(tempfile.gettempdir(), "nuke_mcp", "instances")
    found: dict[int, dict] = {}
    try:
        names = os.listdir(folder)
    except OSError:
        return found
    now = time.time()
    for name in names:
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, name), encoding="utf-8") as fh:
                info = json.load(fh)
        except (OSError, ValueError):
            continue
        if now - float(info.get("heartbeat", 0)) > REGISTRY_STALE_SECONDS:
            continue
        if isinstance(info.get("port"), int):
            found[info["port"]] = info
    return found


def scan_instances(
    host: str = DEFAULT_HOST,
    start_port: int = BASE_PORT,
    count: int = PORT_RANGE,
    timeout: float = 2.0,
) -> list[dict]:
    """Find running Nuke addons on the port range.

    Sessions with a fresh registry entry are listed from it (no socket needed).
    Other ports are probed for a handshake. A port that accepts but does not
    send a NukeMCP handshake is reported with "busy": True (an old addon
    blocked by a render, or another tool using that port).
    """
    registry = registry_instances()
    found = []
    for port in range(start_port, start_port + count):
        if port in registry:
            info = dict(registry[port])
            info.pop("heartbeat", None)
            info["source"] = "registry"
            found.append({"port": port, **info})
            continue
        try:
            sock = socket.create_connection((host, port), timeout=0.3)
        except OSError:
            continue
        try:
            sock.settimeout(timeout)
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(RECV_BUFFER)
                if not chunk:
                    break
                buf += chunk
            if b"\n" in buf:
                info = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
                if not isinstance(info, dict) or "nuke_version" not in info:
                    raise ValueError("not a NukeMCP handshake")
                info.pop("type", None)
                info.pop("commands", None)
                found.append({"port": port, **info})
        except (OSError, ValueError):
            found.append({"port": port, "busy": True,
                          "note": "no NukeMCP handshake: a Nuke busy rendering/blocked by a "
                                  "dialog, or another tool listening on this port"})
        finally:
            try:
                sock.close()
            except OSError:
                pass
    return found


class NukeConnection:
    """Manages a TCP socket connection to the Nuke addon running inside Nuke.

    On connect, reads a handshake message containing Nuke version and variant info.
    Sends JSON commands and receives JSON responses. Supports receiving asynchronous
    event messages pushed by the addon.
    """

    def __init__(self, host: str = DEFAULT_HOST, port: int = DEFAULT_PORT):
        self.host = host
        self.port = port
        self.sock: socket.socket | None = None
        self.handshake: dict | None = None
        self._buffer = b""
        self._response_queue: queue.Queue[dict] = queue.Queue()
        self._event_handler: callable | None = None
        self._reader_thread: threading.Thread | None = None
        self._reader_running = False

    def set_event_handler(self, handler):
        """Set a callback for event messages pushed by the addon.

        The handler receives a dict with keys: type, event_type, data.
        """
        self._event_handler = handler

    def connect(self, retries: int = 3, base_delay: float = 1.0) -> dict:
        """Connect to the Nuke addon and return the handshake data.

        Retries with exponential backoff on failure.
        """
        last_error = None
        for attempt in range(retries):
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.sock.settimeout(10.0)
                self.sock.connect((self.host, self.port))
                self._buffer = b""
                self._response_queue = queue.Queue()
                self.handshake = self._read_message()
                log.info(
                    "Connected to Nuke %s (%s) at %s:%d",
                    self.handshake.get("nuke_version", "unknown"),
                    self.handshake.get("variant", "unknown"),
                    self.host,
                    self.port,
                )
                # Switch to blocking mode and start the reader thread
                self.sock.settimeout(None)
                self._start_reader()
                return self.handshake
            except (OSError, json.JSONDecodeError, TimeoutError) as e:
                last_error = e
                self._close_socket()
                if attempt < retries - 1:
                    delay = base_delay * (2**attempt)
                    log.warning(
                        "Connection attempt %d failed: %s. Retrying in %.1fs...",
                        attempt + 1,
                        e,
                        delay,
                    )
                    time.sleep(delay)

        raise NukeConnectionError(
            f"Failed to connect to Nuke addon at {self.host}:{self.port} "
            f"after {retries} attempts: {last_error}"
        )

    def ensure_connected(self) -> dict:
        """Connect lazily: try the current port, else the first Nuke found.

        Lets the MCP server start before Nuke, and recover when the Nuke it
        was talking to is closed.
        """
        if self.sock:
            return self.handshake
        try:
            return self.connect(retries=1)
        except NukeConnectionError:
            pass
        for inst in scan_instances(self.host):
            if inst.get("busy"):
                continue
            self.port = inst["port"]
            try:
                return self.connect(retries=1)
            except NukeConnectionError:
                continue
        raise NukeConnectionError(
            f"No Nuke addon found on ports {BASE_PORT}-{BASE_PORT + PORT_RANGE - 1}. "
            "Open Nuke and start NukeMCP (Nodes > NukeMCP > Start Server)."
        )

    def switch(self, port: int) -> dict:
        """Point this connection at the Nuke addon on another port."""
        if self.sock and port == self.port:
            return self.handshake
        self.disconnect()
        old_port, self.port = self.port, port
        try:
            return self.connect(retries=1)
        except NukeConnectionError:
            self.port = old_port
            raise

    def send(self, command: dict, timeout: float = 10.0) -> dict:
        """Send a JSON command and return the JSON response.

        Reconnects transparently if the addon dropped the socket since the last
        command. Without this, a single drop leaves the connection unusable for
        the lifetime of the server process, and every tool fails until it is
        restarted.
        """
        msg = json.dumps(command) + "\n"

        for attempt in range(2):
            if self.sock is None:
                self.ensure_connected()
            try:
                self.sock.sendall(msg.encode("utf-8"))
            except OSError as e:
                self._reset()
                if attempt == 0:
                    log.warning("Send failed (%s), reconnecting and retrying", e)
                    continue
                raise NukeConnectionError(f"Communication error: {e}") from e

            try:
                return self._response_queue.get(timeout=timeout)
            except queue.Empty:
                # The addon may still deliver this response later, which would
                # then be handed back as the answer to the *next* command. Drop
                # the connection so the following call starts from a clean state.
                self._reset()
                raise NukeConnectionError(
                    f"Timeout waiting for response after {timeout}s"
                ) from None

        raise NukeConnectionError("Failed to send command to Nuke addon")

    def send_command(self, cmd_type: str, params: dict | None = None, timeout: float = 10.0) -> dict:
        """Send a command and return the result, raising on error."""
        response = self.send({"type": cmd_type, "params": params or {}}, timeout=timeout)
        if response["status"] == "error":
            message = response["error"]
            if response.get("rolled_back") is True:
                message += " (rolled back: the script was left unchanged)"
            elif response.get("rolled_back"):
                message += " (partially rolled back: %s)" % response["rolled_back"]
            raise RuntimeError(message)
        return response["result"]

    def disconnect(self):
        """Cleanly disconnect from the Nuke addon."""
        self._reset()
        self.handshake = None
        log.info("Disconnected from Nuke addon")

    @property
    def is_connected(self) -> bool:
        return self.sock is not None

    def _start_reader(self):
        """Start the background thread that reads all incoming messages."""
        self._reader_running = True
        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reset(self):
        """Tear down the socket, reader thread, and any stale buffered state."""
        self._reader_running = False
        # Close first: this unblocks the reader thread's blocking recv().
        self._close_socket()
        thread = self._reader_thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        self._reader_thread = None
        self._buffer = b""
        # Discard late responses so they can't be returned to a later command.
        while True:
            try:
                self._response_queue.get_nowait()
            except queue.Empty:
                break

    def _reader_loop(self):
        """Background loop: read messages and route events vs responses."""
        while self._reader_running:
            try:
                msg = self._read_message()
            except (NukeConnectionError, OSError, AttributeError):
                # Nuke closed or we disconnected; next send() reconnects
                self._close_socket()
                break
            if msg.get("type") == "event":
                if self._event_handler:
                    try:
                        self._event_handler(msg)
                    except Exception:
                        log.exception("Event handler error")
            else:
                self._response_queue.put(msg)

    def _read_message(self) -> dict:
        """Read a newline-delimited JSON message from the socket."""
        while b"\n" not in self._buffer:
            chunk = self.sock.recv(RECV_BUFFER)
            if not chunk:
                self._close_socket()
                raise NukeConnectionError("Connection closed by Nuke addon")
            self._buffer += chunk

        line, self._buffer = self._buffer.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def _close_socket(self):
        if self.sock:
            try:
                self.sock.close()
            except OSError:
                pass
            self.sock = None
