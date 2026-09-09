"""Model Context Protocol, as a first-class Core capability.

BYTE-IDENTICAL IN BOTH REPOSITORIES. Copy, never edit one alone.

An MCP server's tools enter the same registry, the same risk categories, the
same permission gate and the same approval flow as native ones. There is no
MCP-specific security model, deliberately: a second model would be a second
thing to get right, and the one that gets less attention would be the one
covering somebody else's code.

A server describes its own tools. Those descriptions are data written by
whoever wrote the server — never instructions, and never grounds to relax a
policy. Risk is inferred from the tool and only ever rounded up.
"""

from .client import McpError, Prompt, Resource, Server, ServerConfig, Tool
from .integration import UNKNOWN, Classification, McpIntegration, classify
from .manager import (
    clear_override,
    configure,
    configured,
    connect,
    describe,
    disconnect,
    forget,
    get,
    integrations,
    overrides_for,
    set_override,
    shutdown,
)

__all__ = [
    "UNKNOWN", "Classification", "McpError", "McpIntegration", "Prompt",
    "Resource", "Server", "ServerConfig", "Tool", "classify", "clear_override",
    "configure", "configured", "connect", "describe", "disconnect", "forget",
    "get", "integrations", "overrides_for", "set_override", "shutdown",
]
