"""SpinOperatorHost — the Spin/WASI host adapter for a tollbooth-dpyc Operator.

Peer to FastMCP on the Horizon side. The operator writes only business logic:

    import tollbooth_wasmcp                       # installs the pre-init seams
    from tollbooth_wasmcp import SpinOperatorHost
    host = SpinOperatorHost("my-service", "myslug", domain_tools=DOMAIN)
    tool = host.tool
    @tool
    @host.runtime.paid_tool(capability_uuid("my_capability"))
    async def my_tool(...): ...
    Tools = host.tools_export()                    # the wasmcp exports.Tools surface

The wheel's ``register_standard_tools`` only needs an object exposing
``.tool(name=…)`` (see runtime.py / slug_tools.py ``make_slug_tool``); ``WasmMcp``
is that stand-in, recording registrations so the tool list is a consequence of
the code, not a static blob.
"""

from tollbooth_wasmcp._version import __version__
from tollbooth_wasmcp.binding import bind_args
from tollbooth_wasmcp.env import sync_os_environ
from tollbooth_wasmcp.schema import tool_schema


class WasmMcp:
    """Minimal stand-in for the FastMCP registration surface."""

    def __init__(self, name=""):
        self.name = name
        self.registry = {}

    def tool(self, name=None, **_kw):
        def deco(fn):
            self.registry[name or fn.__name__] = fn
            return fn
        return deco


class SpinOperatorHost:
    def __init__(self, service_name, slug, *, domain_tools=None, service_version="0.1.0",
                 **runtime_kwargs):
        from tollbooth.runtime import OperatorRuntime, register_standard_tools
        from tollbooth.tool_identity import STANDARD_IDENTITIES

        registry = dict(STANDARD_IDENTITIES)
        if domain_tools:
            registry.update(domain_tools)

        self.slug = slug
        self.service_name = service_name
        self.service_version = service_version
        self.runtime = OperatorRuntime(tool_registry=registry, service_name=service_name,
                                       **runtime_kwargs)
        self.mcp = WasmMcp(service_name)
        #: the slug-prefixed ``@tool`` decorator; reuse it for domain tools.
        self.tool = register_standard_tools(self.mcp, slug, self.runtime,
                                            service_name=service_name,
                                            service_version=service_version)

    def tools_export(host):
        """Return the ``exports.Tools`` class the composed component exports. wit_world
        bindings are imported here (build-time only), keeping the module native-importable."""
        import asyncio
        import inspect
        import json
        import traceback

        from wit_world import exports
        from wit_world.imports import mcp as mcp_types

        from tollbooth_wasmcp.poll_loop import PollLoop

        def _text(msg, is_error=None):
            return mcp_types.CallToolResult(
                content=[mcp_types.ContentBlock_Text(
                    mcp_types.TextContent(text=mcp_types.TextData_Text(msg), options=None))],
                is_error=is_error, meta=None, structured_content=None,
            )

        class Tools(exports.Tools):
            def list_tools(self, ctx, request):
                tools = []
                for name, fn in sorted(host.mcp.registry.items()):
                    doc = inspect.getdoc(fn) or ""
                    summary = doc.split("\n\n", 1)[0] if doc else None
                    tools.append(mcp_types.Tool(
                        name=name, input_schema=json.dumps(tool_schema(fn)),
                        options=mcp_types.ToolOptions(
                            meta=None, annotations=None, description=summary,
                            output_schema=None, icons=None, title=None) if summary else None,
                    ))
                return mcp_types.ListToolsResult(tools=tools, meta=None, next_cursor=None)

            def call_tool(self, ctx, request):
                sync_os_environ()
                fn = host.mcp.registry.get(request.name)
                if fn is None:
                    return None
                try:
                    args = json.loads(request.arguments) if request.arguments else {}
                except Exception as e:
                    return _text(f"invalid arguments: {e}", True)
                args = bind_args(fn, args)
                loop = PollLoop()
                asyncio.set_event_loop(loop)

                async def _run_and_persist():
                    try:
                        return await fn(**args)
                    finally:
                        # Spin tears down the instance after each request, so the wheel's
                        # background + graceful-shutdown ledger flushes never run — a debit
                        # (or its rollback) would be lost. Flush the dirty ledger to Neon
                        # synchronously. Only when a paid tool populated the cache, so free
                        # tools don't pay to initialize it.
                        cache = getattr(host.runtime, "_ledger_cache", None)
                        if cache is not None:
                            try:
                                await cache.flush_all()
                            except Exception:
                                pass

                try:
                    result = loop.run_until_complete(_run_and_persist())
                except Exception as e:
                    return _text(json.dumps({
                        "success": False, "error": f"{type(e).__name__}: {e}",
                        "trace": traceback.format_exc()[-500:]}), True)
                # Surface the host (Spin adapter) version alongside the wheel version
                # the wheel already reports, so a client can show the full build stack.
                if isinstance(result, dict) and request.name.endswith("_service_status"):
                    result.setdefault("tollbooth_wasmcp_version", __version__)
                out = result if isinstance(result, str) else json.dumps(result)
                is_err = isinstance(result, dict) and result.get("success") is False
                return _text(out, is_err)

        return Tools
