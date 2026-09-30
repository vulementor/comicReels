"""FBR-2-code-3c authored facade/restart requirements; not executed during coding."""
import threading
from pathlib import Path

import pytest

from agent.services.flow_browser_backend import BrowserFlowBackend
from agent.services.flow_browser_session import FlowProfileConfig
from agent.services.flow_browser_state import BrowserStateStore

PROJECT = '11111111-2222-3333-4444-555555555555'
OPERATION = 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff'


class Driver:
    paid_dispatch_enabled = False
    instances = []

    def __init__(self, config, state_path, owner_key):
        self.config = config
        self.state_path = Path(state_path)
        self.owner_key = owner_key
        self.thread = None
        self.closed = False
        self.calls = []
        Driver.instances.append(self)

    def start(self):
        self.thread = threading.get_ident()
        self.calls.append('start')

    def health(self):
        self.calls.append('health')
        saved = BrowserStateStore(self.state_path, self.owner_key).load()
        return {
            'backend_kind': 'browser',
            'profile': self.config.profile_logical_name,
            'state': 'closed' if self.closed else 'open',
            'ready': not self.closed,
            'session_ready': not self.closed,
            'readiness_scope': 'non_paid_parity',
            'operations_implemented': True,
            'capabilities': {
                'project_open_resume': True,
                'project_create_session': True,
                'project_media_read': True,
                'media_read': True,
                'operation_reconcile': True,
                'upload': True,
                'paid_dispatch': False,
            },
            'paid_dispatch_enabled': False,
            'has_saved_project': saved['project_id'] is not None,
            'pending_intents': 0,
            'reconciliation_required': False,
            'error': None,
        }

    def open_project(self, project_id):
        self.calls.append(('open_project', project_id))
        BrowserStateStore(self.state_path, self.owner_key).set_project(project_id)
        return {'status': 200, 'data': {'projectId': project_id}, 'effect': 'completed'}

    def ensure_session_project(self, title, force_new):
        self.calls.append(('ensure_session_project', title, force_new))
        saved = BrowserStateStore(self.state_path, self.owner_key).load()
        return {'status': 200, 'data': {'projectId': saved['project_id'], 'reused': True},
                'effect': 'completed'}

    def execute(self, command, timeout):
        self.calls.append(('execute', command.rpcid, timeout))
        return {'status': 200, 'effect': 'completed'}

    def close(self):
        self.calls.append('close')
        self.closed = True


@pytest.fixture
def config(tmp_path):
    profile = tmp_path / 'profile'
    profile.mkdir()
    stat = profile.stat()
    return FlowProfileConfig('unit-flow', profile, tmp_path / 'binding.json',
                             (stat.st_dev, stat.st_ino))


@pytest.mark.asyncio
async def test_facade_reports_final_non_paid_capabilities(config, tmp_path):
    Driver.instances.clear()
    backend = BrowserFlowBackend(config=config, state_path=tmp_path / 'state.json',
                                 driver_factory=Driver)
    try:
        await backend.start()
        report = await backend.check_readiness()
        assert backend.ready is True
        assert report['ready'] is True
        assert report['readiness_scope'] == 'non_paid_parity'
        assert report['operations_implemented'] is True
        assert report['capabilities']['upload'] is True
        assert report['capabilities']['operation_reconcile'] is True
        assert report['capabilities']['paid_dispatch'] is False
        assert backend.paid_dispatch_enabled is False
    finally:
        await backend.close()


@pytest.mark.asyncio
async def test_new_backend_instance_resumes_same_state_after_clean_close(config, tmp_path):
    Driver.instances.clear()
    state_path = tmp_path / 'state.json'
    first = BrowserFlowBackend(config=config, state_path=state_path, driver_factory=Driver)
    await first.start()
    await first.open_project(PROJECT)
    first_owner = first.session_owner_key
    first_thread = Driver.instances[-1].thread
    await first.close()

    second = BrowserFlowBackend(config=config, state_path=state_path, driver_factory=Driver)
    try:
        await second.start()
        assert second.session_owner_key == first_owner
        assert Driver.instances[-1].thread != threading.get_ident()
        result = await second.ensure_session_project(title='ignored', force_new=False)
        assert result['data'] == {'projectId': PROJECT, 'reused': True}
        report = await second.check_readiness()
        assert report['has_saved_project'] is True
    finally:
        await second.close()

    assert first_thread is not None


@pytest.mark.asyncio
async def test_facade_keeps_paid_dispatch_disabled_across_restart(config, tmp_path):
    Driver.instances.clear()
    state_path = tmp_path / 'state.json'
    for _ in range(2):
        backend = BrowserFlowBackend(config=config, state_path=state_path,
                                     driver_factory=Driver)
        await backend.start()
        assert backend.paid_dispatch_enabled is False
        assert (await backend.check_readiness())['paid_dispatch_enabled'] is False
        await backend.close()
