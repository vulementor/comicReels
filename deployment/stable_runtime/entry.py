"""Catalogued entries for the ComicReels toolkit and the ThoRemix application."""
import json


SUPPORTED_DEPLOYMENTS = {("service", "comicreels"), ("app", "thoremix")}
REQUIRED_SETTINGS = ["chat_profile_name","api_port","websocket_port"]
CONFIG_SETTINGS = []
CONFIG_FILES = ["config/models.json","config/providers.json"]


def deployment_for_entry(context):
    deployment = context.deployment()
    value = deployment.as_dict()
    if (value["kind"], value["name"]) not in SUPPORTED_DEPLOYMENTS:
        raise ValueError("UNSUPPORTED_CONSUMER_DEPLOYMENT")
    return deployment


def entry_report(context, deployment):
    """Describe declared wiring only; never open a business ledger or start work."""
    value = deployment.as_dict()
    settings = deployment.settings
    missing_settings = [name for name in REQUIRED_SETTINGS if settings.get(name) in (None, "")]
    missing_files = [name for name in CONFIG_FILES if not deployment.data_path(name).is_file()]
    for name in CONFIG_SETTINGS:
        if name not in missing_settings and not deployment.data_path(settings[name]).is_file():
            missing_files.append(name)
    domain_entries = ["server"]
    if value["name"] == "thoremix":
        domain_entries = ["campaign-status", "tick", "dispatch", "desktop", "desktop-smoke", "desktop-command"]
    return {
        "schema": f"stable.{value['kind']}.entry.v1",
        value["kind"]: value["name"], "kind": value["kind"], "name": value["name"],
        "operation": context.entrypoint, "instance_id": deployment.instance_id,
        "release_id": value["release_id"], "channel": value["channel"],
        "enabled": value["enabled"], "home": str(deployment.home),
        "status": ("DISABLED" if not value["enabled"] else
                   "CONFIGURATION_REQUIRED" if missing_settings or missing_files else "DECLARED"),
        "execution_readiness": "NOT_CHECKED", "domain_state": "NOT_READ",
        "supported_entries": ["help", "status", *domain_entries],
        "unsupported_entries": ({"desktop": "UNSUPPORTED_TOOLKIT_DESKTOP"}
                                if value["kind"] == "service" else {}),
        "missing_settings": missing_settings, "missing_config_files": missing_files,
        "profile_roles": sorted(deployment.profiles),
    }


def write_result(context, result):
    from stable_toolkit_runtime.context import atomic_json
    atomic_json(context.instance_dir / "app-result.json", result)
    print(json.dumps(result, sort_keys=True, default=str))


def inspect_entry(context, deployment):
    if (context.entrypoint in {"help", "status"}
            or context.entrypoint == "desktop" and deployment.as_dict()["kind"] == "service"):
        result = entry_report(context, deployment)
        if context.entrypoint == "desktop":
            result.update(status="UNSUPPORTED", error="UNSUPPORTED_TOOLKIT_DESKTOP")
        write_result(context, result)
        return 2 if context.entrypoint == "desktop" else 0
    return None


def binding_from_context(context):
    from agent.private_runtime import PrivateRuntime
    deployment = deployment_for_entry(context)
    value = deployment.as_dict()
    settings = deployment.settings
    flow = settings.get("flow_profile_config")
    return PrivateRuntime(
        instance_id=deployment.instance_id, consumer_kind=value["kind"],
        consumer_name=value["name"], home=deployment.home,
        profiles=deployment.profiles, tool_resolver=context.tool,
        profile_lease_factory=context.resource,
        model_resolver=lambda name: context.models().require_model(name),
        chat_profile_name=settings["chat_profile_name"],
        flow_profile_config=deployment.data_path(flow) if flow else None,
        visible=settings.get("visible", False), api_port=settings["api_port"],
        websocket_port=settings["websocket_port"],
    )


async def serve_comicreels(context):
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
            raise RuntimeError("COMICREELS_SERVER_NOT_STARTED")
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)


_DLL_HANDLES = []


def prepare_private_dependencies(context):
    """Only add catalogued release payloads; never ambient/legacy Python paths."""
    import os
    import sys
    from stable_toolkit_runtime.registry import RegistryError

    def optional(relative):
        try:
            return context.release_path(relative)
        except RegistryError as error:
            if error.code != "DEPENDENCY_UNAVAILABLE":
                raise
            return None

    thirdparty = optional("native/thirdparty")
    if thirdparty is not None:
        if not thirdparty.is_dir():
            raise ValueError("INVALID_PRIVATE_DEPENDENCIES")
        if str(thirdparty) not in sys.path:
            sys.path.append(str(thirdparty))
    if os.name == "nt":
        for relative in ("native/media/ffpyplayer/ffmpeg/bin", "native/media/ffpyplayer/sdl/bin"):
            directory = optional(relative)
            if directory is not None:
                _DLL_HANDLES.append(os.add_dll_directory(str(directory)))


def main(context):
    deployment = deployment_for_entry(context)
    inspected = inspect_entry(context, deployment)
    if inspected is not None:
        return inspected
    consumer_name = deployment.as_dict()["name"]
    allowed = ({"server"} if consumer_name == "comicreels" else
               {"tick", "dispatch", "campaign-status", "desktop", "desktop-smoke", "desktop-command"})
    if context.entrypoint not in allowed:
        raise ValueError("UNSUPPORTED_COMICREELS_ENTRY")
    prepare_private_dependencies(context)
    binding = binding_from_context(context)
    if context.entrypoint in {"desktop", "desktop-smoke", "desktop-command"}:
        from agent.thoremix.managed_desktop import run_child_command, run_managed_desktop
        if context.entrypoint == "desktop-command":
            return run_child_command(context, binding)
        return run_managed_desktop(context, binding, smoke=context.entrypoint == "desktop-smoke")
    if binding.consumer_kind == "service" and context.entrypoint == "server":
        from agent.private_runtime import install_private_runtime
        install_private_runtime(binding)
        import asyncio
        asyncio.run(serve_comicreels(context))
        return 0
    from agent.private_host import run_thoremix
    operation = "status" if context.entrypoint == "campaign-status" else context.entrypoint
    result = run_thoremix(context, binding, operation=operation, job_id="operation")
    write_result(context, result)
    return 0



