"""Shared constants for the NukeMCP addon.

Kept free of Nuke and Qt imports so every module (and the test-suite) can use them.
"""

ADDON_VERSION = "0.2.0"

HOST = "127.0.0.1"
DEFAULT_PORT = 54321
PORT_RANGE = 10  # one port per running Nuke session: 54321-54330

# Every mutating command runs inside an undo group whose label starts with this
# prefix, so undo_agent_session can walk back the agent's work and stop at the
# first step the user made by hand.
UNDO_PREFIX = "MCP: "

# Set in Nuke's own process once the server has bound its port. Anything Nuke
# launches (e.g. a Claude panel spawning the CLI) inherits it, so an MCP server
# started from inside a Nuke session talks to that session and not to whichever
# one happens to own the default port.
ENV_PORT = "NUKE_MCP_PORT"

# Heartbeat for the on-disk instance registry (%TEMP%/nuke_mcp/instances).
HEARTBEAT_SECONDS = 10

CONSOLE_MAX_LINES = 5000
JOURNAL_KEEP_FILES = 30
