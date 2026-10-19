"""Nuke menu integration for NukeMCP.

Place this file and the nuke_mcp_addon folder in your .nuke directory or NUKE_PATH.
If you already have a menu.py, append the block below to it instead.

The server starts automatically in every GUI Nuke session. Each session takes
the first free port in 54321-54330, so several Nukes can be open at once.
"""

import nuke

try:
    import nuke_mcp_addon
    nuke_mcp_addon.start(show_panel=False)
    nuke_mcp_menu = nuke.menu("Nodes").addMenu("NukeMCP")
    nuke_mcp_menu.addCommand(
        "Show Panel",
        "import nuke_mcp_addon; nuke_mcp_addon.start()",
    )
except Exception as e:
    print("NukeMCP: could not start: %s" % e)
