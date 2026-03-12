# SPDX-FileCopyrightText: 2026 Bentley Systems, Incorporated
#
# SPDX-License-Identifier: Apache-2.0

"""
Entry point for the evo-mcp console script.

Allows the server to be started via:
    evo-mcp          (after pip install)
    uvx --from ...   (without local install)
    python -m evo_mcp
"""

import logging


def main():
    # Importing mcp_tools triggers FastMCP creation and tool registration
    import mcp_tools

    logger = logging.getLogger("evo_mcp")
    logger.info("Starting Evo MCP Server in %s mode", mcp_tools.TRANSPORT.upper())

    if mcp_tools.TRANSPORT == "http":
        logger.info(
            "HTTP server will listen on %s:%s",
            mcp_tools.HTTP_HOST,
            mcp_tools.HTTP_PORT,
        )
        mcp_tools.mcp.run(
            transport="http",
            host=mcp_tools.HTTP_HOST,
            port=mcp_tools.HTTP_PORT,
        )
    else:
        mcp_tools.mcp.run()


if __name__ == "__main__":
    main()
