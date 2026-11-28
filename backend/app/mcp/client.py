import asyncio
import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional

from app.mcp.postgres_server import MCP_TOOLS, handle_json_rpc_message

logger = logging.getLogger("mcp.client")


class MCPPostgresClient:
    """
    Async JSON-RPC 2.0 MCP client for finalairajmaster-postgres-mcp.

    Uses a warm persistent stdio subprocess in local/Docker/HF Spaces environments,
    and falls back cleanly to in-process JSON-RPC dispatch if subprocess stdio is
    unavailable (e.g., restricted serverless runtimes or Windows SelectorEventLoop).
    """

    def __init__(self) -> None:
        self._proc: Optional[asyncio.subprocess.Process] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = asyncio.Lock()
        self._req_id = 0
        self._initialized = False
        self._server_info: Dict[str, Any] = {
            "name": "finalairajmaster-postgres-mcp",
            "version": "1.0.0",
            "protocolVersion": "2024-11-05",
        }
        self._backend_dir = os.path.abspath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
        )

    def _next_id(self) -> int:
        self._req_id += 1
        return self._req_id

    async def _ensure_stdio_process(self) -> bool:
        """Starts and initializes the stdio MCP subprocess if not already running."""
        if os.getenv("VERCEL") or os.getenv("MCP_INPROCESS_ONLY") == "1":
            return False

        current_loop = asyncio.get_running_loop()
        if (
            self._proc is not None
            and self._proc.returncode is None
            and self._initialized
            and self._loop is current_loop
            and not current_loop.is_closed()
        ):
            return True

        await self._terminate_process()

        try:
            env = os.environ.copy()
            env.setdefault("PYTHONUNBUFFERED", "1")
            self._loop = current_loop
            self._proc = await asyncio.create_subprocess_exec(
                sys.executable,
                "-m",
                "app.mcp.postgres_server",
                cwd=self._backend_dir,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )

            init_resp = await self._send_stdio_rpc(
                "initialize",
                {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "rajmaster-langgraph-client", "version": "1.0.0"},
                },
                timeout=4.0,
            )
            if "result" not in init_resp:
                raise RuntimeError(f"MCP initialize failed: {init_resp}")

            result = init_resp["result"]
            self._server_info = {
                "name": result.get("serverInfo", {}).get("name", "finalairajmaster-postgres-mcp"),
                "version": result.get("serverInfo", {}).get("version", "1.0.0"),
                "protocolVersion": result.get("protocolVersion", "2024-11-05"),
            }

            await self._send_stdio_notification("notifications/initialized")
            self._initialized = True
            logger.info("Connected to MCP stdio server: %s", self._server_info["name"])
            return True
        except Exception as e:
            logger.debug("MCP stdio spawn unavailable (%s); using in-process JSON-RPC mode.", e)
            await self._terminate_process()
            return False

    async def _send_stdio_rpc(
        self, method: str, params: Optional[Dict[str, Any]] = None, timeout: float = 5.0
    ) -> Dict[str, Any]:
        if not self._proc or not self._proc.stdin or not self._proc.stdout:
            raise RuntimeError("MCP stdio process is not running.")

        msg: Dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            msg["params"] = params

        payload = (json.dumps(msg) + "\n").encode("utf-8")
        self._proc.stdin.write(payload)
        await self._proc.stdin.drain()

        raw_line = await asyncio.wait_for(self._proc.stdout.readline(), timeout=timeout)
        if not raw_line:
            raise RuntimeError("MCP stdio server closed stdout unexpectedly.")
        return json.loads(raw_line.decode("utf-8"))

    async def _send_stdio_notification(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> None:
        if not self._proc or not self._proc.stdin:
            return
        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        await self._proc.stdin.drain()

    async def _dispatch_inprocess(
        self, method: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        req: Dict[str, Any] = {"jsonrpc": "2.0", "id": self._next_id(), "method": method}
        if params is not None:
            req["params"] = params
        resp = await asyncio.to_thread(handle_json_rpc_message, req)
        return resp or {}

    async def _terminate_process(self) -> None:
        self._initialized = False
        if self._proc is not None:
            try:
                if self._proc.stdin and not self._proc.stdin.is_closing():
                    self._proc.stdin.close()
                if self._proc.returncode is None:
                    self._proc.terminate()
                    try:
                        await asyncio.wait_for(self._proc.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        self._proc.kill()
            except Exception:
                pass
            finally:
                self._proc = None
                self._loop = None

    async def call_tool(self, tool_name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Executes an MCP tool over JSON-RPC 2.0 and returns parsed tool output plus transport info."""
        args = arguments or {}
        async with self._lock:
            transport = "inprocess-jsonrpc"
            rpc_resp: Dict[str, Any]

            if await self._ensure_stdio_process():
                try:
                    rpc_resp = await self._send_stdio_rpc(
                        "tools/call",
                        {"name": tool_name, "arguments": args},
                        timeout=6.0,
                    )
                    transport = "stdio-jsonrpc"
                except Exception as e:
                    logger.warning("MCP stdio call failed (%s), falling back to in-process JSON-RPC.", e)
                    await self._terminate_process()
                    rpc_resp = await self._dispatch_inprocess(
                        "tools/call", {"name": tool_name, "arguments": args}
                    )
            else:
                rpc_resp = await self._dispatch_inprocess(
                    "tools/call", {"name": tool_name, "arguments": args}
                )

        if "error" in rpc_resp:
            raise RuntimeError(rpc_resp["error"].get("message", "Unknown MCP JSON-RPC error"))

        result = rpc_resp.get("result", {})
        content = result.get("content", [])
        text_payload = content[0].get("text", "{}") if content else "{}"
        is_error = bool(result.get("isError", False))

        if is_error:
            return {
                "ok": False,
                "error": text_payload,
                "tool": tool_name,
                "transport": transport,
                "server": self._server_info,
            }

        try:
            parsed = json.loads(text_payload)
        except Exception:
            parsed = {"raw": text_payload}

        return {
            "ok": True,
            "data": parsed,
            "tool": tool_name,
            "transport": transport,
            "server": self._server_info,
        }

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Returns the list of MCP tools advertised by the server."""
        async with self._lock:
            if await self._ensure_stdio_process():
                try:
                    resp = await self._send_stdio_rpc("tools/list", timeout=4.0)
                    return resp.get("result", {}).get("tools", MCP_TOOLS)
                except Exception:
                    await self._terminate_process()
            resp = await self._dispatch_inprocess("tools/list")
            return resp.get("result", {}).get("tools", MCP_TOOLS)

    async def health_check(self) -> Dict[str, Any]:
        """Verifies live MCP protocol readiness without exposing internal schema/table counts publicly."""
        try:
            tools = await self.list_tools()
            probe = await self.call_tool("get_administrative_lineage", {"entity_name_or_pincode": "Jaipur"})
            return {
                "status": "online" if probe.get("ok") else "degraded",
                "server": self._server_info,
                "transport": probe.get("transport", "inprocess-jsonrpc"),
                "tools_count": len(tools),
                "error": probe.get("error"),
            }
        except Exception as e:
            return {
                "status": "offline",
                "server": self._server_info,
                "transport": "unavailable",
                "tools_count": 0,
                "error": "MCP unavailable",
            }

    async def close(self) -> None:
        async with self._lock:
            await self._terminate_process()


mcp_client = MCPPostgresClient()
