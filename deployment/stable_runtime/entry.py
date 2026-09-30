"""Catalogued entry for independent Comic and ThoRemix deployments."""
from agent.private_runtime import PrivateRuntime, install_private_runtime


def binding_from_context(context):
    deployment = context.deployment()
    value = deployment.as_dict()
    if value["kind"] != "app" or value["name"] not in {"comic", "thoremix"}:
        raise ValueError("UNSUPPORTED_COMIC_APP")
    settings = deployment.settings
    flow = settings.get("flow_profile_config")
    return PrivateRuntime(
        instance_id=deployment.instance_id, app_kind=value["name"], home=deployment.home,
        profiles=deployment.profiles, tool_resolver=context.tool,
        profile_lease_factory=context.resource,
        model_resolver=lambda name: context.models().require_model(name),
        chat_profile_name=settings["chat_profile_name"],
        flow_profile_config=deployment.data_path(flow) if flow else None,
        visible=settings.get("visible", False), api_port=settings["api_port"],
        websocket_port=settings["websocket_port"],
    )


async def serve_comic(context):
    # Binding must be installed before importing agent.config or the ASGI app.
    import asyncio
    import uvicorn
    from agent import config
    from agent.main import app
    from agent.services.flow_client import get_flow_client

    server = uvicorn.Server(uvicorn.Config(
        app, host=config.API_HOST, port=config.API_PORT, reload=False, workers=1,
    ))

    async def observe():
        previous = None
        while not server.should_exit:
            if context.is_draining():
                server.should_exit = True
                return
            if server.started:
                client = get_flow_client()
                ready = bool(client.connected)
                current = (ready, "BACKEND_READY" if ready else "BACKEND_NOT_READY")
                if current != previous:
                    context.report_readiness(*current)
                    previous = current
            await asyncio.sleep(0.25)

    monitor = asyncio.create_task(observe())
    try:
        await server.serve()
        if not server.started:
            raise RuntimeError("COMIC_SERVER_NOT_STARTED")
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)


def main(context):
    binding = binding_from_context(context)
    if binding.app_kind == "comic" and context.entrypoint == "server":
        install_private_runtime(binding)
        import asyncio
        asyncio.run(serve_comic(context))
        return 0
    if binding.app_kind != "thoremix" or context.entrypoint not in {"tick", "dispatch", "status"}:
        raise ValueError("UNSUPPORTED_COMIC_ENTRY")
    from agent.private_host import run_thoremix
    result = run_thoremix(context, binding, operation=context.entrypoint, job_id="operation")
    from stable_toolkit_runtime.context import atomic_json
    atomic_json(context.instance_dir / "app-result.json", result)
    return 0
