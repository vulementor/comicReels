"""FBR-0 safety contracts; no external website or authenticated profile used."""
import json
import subprocess
import sys
from dataclasses import replace

import pytest


def implementation():
    from agent.services import flow_browser_session
    return flow_browser_session


@pytest.fixture
def config(tmp_path):
    m = implementation()
    profile = tmp_path / "profile"
    profile.mkdir()
    source = tmp_path / "binding.json"
    source.write_text(json.dumps({"schema_version": 1, "browser_kind": "camoufox",
                                 "profile_logical_name": "flow-browser",
                                 "user_data_dir": str(profile)}))
    return m.FlowProfileConfig.load(source)


class Page:
    url = "about:blank"
    context = None
    closed = False

    def goto(self, url, **kwargs):
        assert url == "https://flow.google.com/"
        self.url = url

    def is_closed(self):
        return self.closed

    def aria_snapshot(self, **kwargs):
        return '- button "Test account surface"\n- button "Test project surface"'


class Context:
    def __init__(self):
        self.page = Page()
        self.page.context = self
        self.pages = [self.page]
        self.closed = False
        self.fail_close = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        if self.fail_close:
            raise RuntimeError("private close details")
        self.closed = True
        self.page.closed = True


def factory(config, contexts):
    def create(**kwargs):
        assert kwargs['persistent_context'] is True
        assert kwargs['headless'] is False
        assert kwargs['main_world_eval'] is True
        assert kwargs['user_data_dir'] == str(config.user_data_dir)
        context = Context()
        contexts.append(context)
        return context
    return create


def signed_in(_):
    return implementation().AuthObservation("authenticated", identity="private-account-a")


def test_missing_profile_is_not_created(tmp_path):
    binding = tmp_path / 'binding.json'
    binding.write_text(json.dumps({"schema_version": 1, "browser_kind": "camoufox",
                                  "profile_logical_name": "flow-browser",
                                  "user_data_dir": str(tmp_path / 'missing')}))
    with pytest.raises(implementation().FlowBrowserError, match="PROFILE_NOT_FOUND"):
        implementation().FlowProfileConfig.load(binding)
    assert not (tmp_path / 'missing').exists()


def test_background_provider_keeps_profile_but_launches_headless(config):
    seen=[]
    def create(**kwargs):
        seen.append(kwargs)
        return Context()
    with implementation().FlowBrowserSessionProvider(config,context_factory=create,visible=False) as provider:
        assert provider.session is not None
    assert seen[0]['headless'] is True
    assert seen[0]['user_data_dir']==str(config.user_data_dir)


def test_profile_config_repr_does_not_expose_local_path(config):
    assert str(config.user_data_dir) not in repr(config)


def test_lease_is_exclusive_between_processes(config):
    m = implementation()
    with m.FlowProfileLease(config):
        child = subprocess.run([sys.executable, '-c',
            ('from agent.services.flow_browser_session import FlowProfileConfig, FlowProfileLease, FlowBrowserError; '
            'import sys\n'
            'try:\n'
            ' with FlowProfileLease(FlowProfileConfig.load(sys.argv[1])): pass\n'
            'except FlowBrowserError as e:\n'
            ' print(e.code); sys.exit(23)\n'), str(config.source_path)],
            capture_output=True, text=True, timeout=15, check=False)
        assert child.returncode == 23, child.stderr
        assert child.stdout.strip() == 'PROFILE_BUSY'
    with m.FlowProfileLease(config):
        pass


def test_login_helper_marker_is_not_reclaimed(config):
    marker = config.user_data_dir / '.gptfp-runtime.lock'
    marker.write_text('unknown legacy owner')
    with (pytest.raises(implementation().FlowBrowserError, match='PROFILE_RECONCILE_REQUIRED'),
          implementation().FlowProfileLease(config)):
        pass
    assert marker.read_text() == 'unknown legacy owner'


def test_stale_windows_parent_lock_is_quarantined_before_browser_open(config):
    if implementation().os.name != 'nt':
        pytest.skip('Firefox parent.lock reconciliation is Windows-only')
    lock=config.user_data_dir/'parent.lock'
    lock.touch()
    contexts=[]
    provider=implementation().FlowBrowserSessionProvider(
        config,context_factory=factory(config,contexts),auth_probe=signed_in)
    with provider:
        assert provider.session is not None
    assert not lock.exists()
    reconciled=list(config.user_data_dir.glob('.parent.lock.reconciled-*'))
    assert len(reconciled)==1


def test_provider_wraps_existing_page_and_reopens_same_profile(config):
    m = implementation()
    contexts = []
    provider = m.FlowBrowserSessionProvider(config, context_factory=factory(config, contexts),
                                            auth_probe=signed_in)
    for _ in range(2):
        provider.open()
        assert provider.session.page is contexts[-1].page
        health = provider.capture_health()
        assert health['ready'] is True
        assert health['semantic_node_count'] == 2
        assert health['authentication'] == 'authenticated'
        assert health['lease_held'] is True
        assert 'private-account-a' not in json.dumps(health)
        assert str(config.user_data_dir) not in json.dumps(health)
        provider.close()
        assert contexts[-1].closed
        assert provider.health()['lease_held'] is False
        assert provider.health()['ready'] is False
    assert len(contexts) == 2


def test_no_auth_probe_never_claims_authenticated(config):
    m = implementation()
    provider = m.FlowBrowserSessionProvider(config, context_factory=factory(config, []))
    with provider:
        health = provider.capture_health()
        assert health['ready'] is False
        assert health['authentication'] == 'unknown'


def test_identity_change_across_reopen_is_blocked(config):
    m = implementation()
    identity = ['account-a']
    provider = m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
        auth_probe=lambda _: m.AuthObservation('authenticated', identity=identity[0]))
    with provider:
        assert provider.capture_health()['ready'] is True
    identity[0] = 'account-b'
    with provider:
        result = provider.capture_health()
        assert result['ready'] is False
        assert result['error'] == 'IDENTITY_CHANGED'


def test_auth_claim_without_identity_is_unknown(config):
    m = implementation()
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
        auth_probe=lambda _: m.AuthObservation('authenticated')) as provider:
        assert provider.capture_health()['ready'] is False


def test_capture_error_is_sanitized_and_close_releases_lease(config):
    m = implementation()
    def fail(_):
        raise RuntimeError('cookie=secret https://flow.google.com/?token=private')
    provider = m.FlowBrowserSessionProvider(config, context_factory=factory(config, []), auth_probe=fail)
    with provider:
        health = provider.capture_health()
        assert not health['ready']
        assert health['error'] == 'OBSERVATION_FAILED'
        assert 'secret' not in json.dumps(health)
    with m.FlowProfileLease(config):
        pass


def test_close_failure_retains_exclusive_lease_until_success(config):
    m = implementation()
    contexts = []
    provider = m.FlowBrowserSessionProvider(config, context_factory=factory(config, contexts))
    provider.open()
    contexts[0].fail_close = True
    with pytest.raises(m.FlowBrowserError, match='CLOSE_UNCERTAIN'):
        provider.close()
    assert provider.health()['lease_held']
    with pytest.raises(m.FlowBrowserError, match='PROFILE_BUSY'), m.FlowProfileLease(config):
        pass
    with pytest.raises(m.FlowBrowserError, match='CLOSE_UNCERTAIN'):
        provider.open()
    contexts[0].fail_close = False
    provider.close()
    with m.FlowProfileLease(config):
        pass


def test_navigation_error_closes_owned_context_and_sanitizes(config):
    m = implementation()
    contexts = []
    def create(**kwargs):
        context = factory(config, contexts)(**kwargs)
        def fail(*args, **kwargs):
            raise RuntimeError('private URL or cookie')
        context.page.goto = fail
        return context
    provider = m.FlowBrowserSessionProvider(config, context_factory=create)
    with pytest.raises(m.FlowBrowserError, match='OPEN_FAILED'):
        provider.open()
    assert contexts[0].closed
    with m.FlowProfileLease(config):
        pass


def test_external_page_close_invalidates_previous_readiness(config):
    m = implementation()
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
                                      auth_probe=signed_in) as provider:
        assert provider.capture_health()['ready']
        provider.session.page.closed = True
        assert not provider.health()['ready']


def test_unsupported_semantic_surface_cannot_be_ready(config):
    m = implementation()
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
                                      auth_probe=signed_in) as provider:
        provider.session.page.aria_snapshot = None
        assert not provider.capture_health()['ready']


def test_host_change_cannot_claim_flow_authentication(config):
    m = implementation()
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
                                      auth_probe=signed_in) as provider:
        provider.session.page.url = 'https://accounts.google.com/?private=1'
        health = provider.capture_health()
        assert not health['ready']
        assert health['authentication'] == 'unknown'
        assert 'private' not in json.dumps(health)


def test_profile_directory_replacement_is_rejected(config):
    m = implementation()
    # Different inode: the binding must not silently accept a replaced identity directory.
    replaced = replace(config, directory_identity=(-1, -1))
    with pytest.raises(m.FlowBrowserError, match='PROFILE_CHANGED'), m.FlowProfileLease(replaced):
        pass


def test_crashed_owner_requires_reconciliation_even_after_os_unlock(config):
    m = implementation()
    child = subprocess.run([sys.executable, '-c',
        ('from agent.services.flow_browser_session import FlowProfileConfig, FlowProfileLease; '
        'import os,sys; lease=FlowProfileLease(FlowProfileConfig.load(sys.argv[1])); '
        'lease.acquire(); os._exit(0)'), str(config.source_path)],
        capture_output=True, text=True, timeout=15, check=False)
    assert child.returncode == 0, child.stderr
    with pytest.raises(m.FlowBrowserError, match='PROFILE_RECONCILE_REQUIRED'), m.FlowProfileLease(config):
        pass


def test_passive_health_does_not_reuse_cached_authenticated_readiness(config):
    m = implementation()
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
                                      auth_probe=signed_in) as provider:
        assert provider.capture_health()['ready']
        # A passive diagnostic must not authorize a later action using old identity evidence.
        assert not provider.health()['ready']
        assert provider.health()['authentication'] == 'unknown'


def test_identity_change_latches_even_if_account_switches_back(config):
    m = implementation()
    identity = ['a']
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, []),
        auth_probe=lambda _: m.AuthObservation('authenticated', identity=identity[0])) as provider:
        assert provider.capture_health()['ready']
        identity[0] = 'b'
        assert provider.capture_health()['error'] == 'IDENTITY_CHANGED'
        identity[0] = 'a'
        assert provider.capture_health()['error'] == 'IDENTITY_CHANGED'


def test_async_page_is_rejected_and_context_closed(config):
    m = implementation()
    contexts = []
    def create(**kwargs):
        context = factory(config, contexts)(**kwargs)
        async def navigate(*args, **kwargs):
            raise AssertionError('Must not be awaited or invoked')
        context.page.goto = navigate
        return context
    provider = m.FlowBrowserSessionProvider(config, context_factory=create)
    with pytest.raises(m.FlowBrowserError, match='OPEN_FAILED'):
        provider.open()
    assert contexts[0].closed
    assert not provider.health()['lease_held']


def test_context_entry_failure_calls_cleanup_before_releasing(config):
    m = implementation()
    class EntryFailure(Context):
        def __enter__(self):
            raise RuntimeError('private startup detail')
    context = EntryFailure()
    provider = m.FlowBrowserSessionProvider(config, context_factory=lambda **_: context)
    with pytest.raises(m.FlowBrowserError, match='OPEN_FAILED'):
        provider.open()
    assert context.closed
    with m.FlowProfileLease(config):
        pass


def test_wrong_thread_cannot_close_owners_browser(config):
    from concurrent.futures import ThreadPoolExecutor
    m = implementation()
    with m.FlowBrowserSessionProvider(config, context_factory=factory(config, [])) as provider:
        with (ThreadPoolExecutor(max_workers=1) as pool,
              pytest.raises(m.FlowBrowserError, match='WRONG_OWNER_THREAD')):
            pool.submit(provider.close).result()
        assert provider.health()['lease_held']
