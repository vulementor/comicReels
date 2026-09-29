import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent.services import flow_batch as fb

PID = '11111111-2222-3333-4444-555555555555'


def backend(tmp_path, driver):
    from agent.services.flow_browser_backend import BrowserFlowBackend
    config = SimpleNamespace(profile_logical_name='test', user_data_dir=tmp_path,
                             source_path=Path(tmp_path) / 'config.json')
    return BrowserFlowBackend(config=config, state_path=tmp_path / 'state.json', driver_factory=lambda *_: driver)


class Driver:
    def __init__(self):
        self.calls = []
        self.gate = None
        self.entered = threading.Event()

    def record(self, name):
        self.calls.append((name, threading.get_ident()))

    def start(self):
        self.record('start')

    def health(self):
        self.record('health')
        return {'ready': True}

    def execute(self, command, timeout):
        self.record('execute')
        self.entered.set()
        if self.gate:
            assert self.gate.wait(5)
        return {'status': 200, 'data': 'read', 'effect': 'completed'}

    def open_project(self, pid):
        self.record('open')
        return {'status': 200, 'project_id': pid}

    def close(self):
        self.record('close')


@pytest.mark.asyncio
async def test_start_commands_and_close_use_one_owner_thread(tmp_path):
    driver = Driver()
    value = backend(tmp_path, driver)
    await value.start()
    assert value.ready and not value.paid_dispatch_enabled
    await asyncio.gather(*[value.execute('batch_rpc', {'rpcid': fb.RPC_PROJECT_MEDIA,
        'freq': fb.project_media_request(PID)}) for _ in range(3)])
    await value.open_project(PID)
    await value.close()
    assert len({thread for _, thread in driver.calls}) == 1
    assert driver.calls[0][1] != threading.get_ident()
    assert driver.calls[-1][0] == 'close' and not value.ready


@pytest.mark.asyncio
async def test_cancelled_await_does_not_cancel_effect_and_shutdown_drains_it(tmp_path):
    driver = Driver()
    driver.gate = threading.Event()
    value = backend(tmp_path, driver)
    await value.start()
    pending = asyncio.create_task(value.execute('batch_rpc', {
        'rpcid': fb.RPC_PROJECT_MEDIA, 'freq': fb.project_media_request(PID)}))
    for _ in range(100):
        if driver.entered.is_set(): break
        await asyncio.sleep(.01)
    assert driver.entered.is_set()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError): await pending
    closing = asyncio.create_task(value.close())
    await asyncio.sleep(.02)
    assert not closing.done() and all(name != 'close' for name, _ in driver.calls)
    driver.gate.set()
    await closing
    assert driver.calls[-1][0] == 'close'


@pytest.mark.asyncio
async def test_paid_request_and_mixed_envelope_do_not_reach_driver(tmp_path):
    driver = Driver()
    value = backend(tmp_path, driver)
    await value.start()
    result = await value.execute('batch_rpc', {'rpcid': fb.RPC_GEN_IMAGE,
        'freq': fb.build_envelope(fb.RPC_GEN_IMAGE, [])})
    assert result['effect'] == 'not_submitted' and result.get('error')
    assert not any(name == 'execute' for name, _ in driver.calls)
    await value.close()


@pytest.mark.asyncio
async def test_close_failure_retains_owner_for_explicit_close_retry(tmp_path):
    driver = Driver()
    original = driver.close
    def fail(): raise RuntimeError('PRIVATE')
    driver.close = fail
    value = backend(tmp_path, driver)
    await value.start()
    with pytest.raises(Exception, match='CLOSE_UNCERTAIN'): await value.close()
    result = await value.execute('batch_rpc', {'rpcid': fb.RPC_PROJECT_MEDIA,
        'freq': fb.project_media_request(PID)})
    assert result['effect'] == 'not_submitted'
    driver.close = original
    await value.close()
    assert driver.calls[-1][0] == 'close'
