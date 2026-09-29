"""Execute the shipped browser JS with a chunked stream; never contact a service."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

PROJECT = '487247a1-00f4-4de3-83c1-4c16ce834b93'
SCRIPT = Path(__file__).parents[2] / 'agent/services/flow_read_replay.js'


@pytest.mark.parametrize('scenario,expected', [
    ('complete', None), ('oversize', 'BODY_BUDGET'), ('read_error', 'BODY_INCOMPLETE'),
    ('timeout', 'BODY_INCOMPLETE'), ('http_error', 'HTTP_REJECTED'),
    ('wrong_origin', 'SESSION_UNVERIFIED'), ('missing_auth', 'SESSION_UNVERIFIED'),
])
def test_browser_read_is_bounded_complete_and_keeps_auth_inside_page(scenario, expected):
    node = shutil.which('node')
    assert node, 'Node is required to verify the browser stream implementation'
    harness = r'''
const scenario = SCENARIO;
globalThis.location = {origin: scenario === 'wrong_origin' ? 'https://wrong.invalid' :
  'https://flow.google.com', pathname: '/project/PROJECT'};
globalThis.document = {documentElement: {lang: 'vi-VN'}};
globalThis.WIZ_global_data = scenario === 'missing_auth' ? {} :
  {SNlM0e: 'PRIVATE_TOKEN', FdrFJe: 'PRIVATE_SESSION', cfb2h: 'build'};
let calls = 0, reads = 0, cancellations = 0, released = 0, contract = false;
const originalTimer = setTimeout;
if (scenario === 'timeout') globalThis.setTimeout = (fn) => originalTimer(fn, 10);
globalThis.fetch = async (url, options) => {
  calls++;
  const freq = JSON.parse(options.body.get('f.req'));
  contract = options.credentials === 'include' && options.redirect === 'error' &&
    options.body.get('at') === 'PRIVATE_TOKEN' && freq.length === 1 &&
    freq[0].length === 1 && freq[0][0][0] === 'Zzl0ze' &&
    url.startsWith('/_/AiSandboxAngularFrontend/data/batchexecute?rpcids=Zzl0ze');
  return {status: scenario === 'http_error' ? 403 : 200, body: {getReader: () => ({
    read: async () => {
      reads++;
      if (scenario === 'read_error') throw new Error('PRIVATE_TOKEN');
      if (scenario === 'timeout') return new Promise((resolve, reject) =>
        options.signal.addEventListener('abort', () => reject(new Error('aborted'))));
      if (scenario === 'oversize') return {done: false, value: new Uint8Array(300000)};
      return reads <= 2 ? {done: false, value: new TextEncoder().encode(reads === 1 ? 'hello ' : 'world')} :
        {done: true};
    },
    cancel: async () => {cancellations++;},
    releaseLock: () => {released++;},
  })}};
};
(async () => {
  const result = await (SCRIPT)({projectId: 'PROJECT'});
  process.stdout.write(JSON.stringify({result, calls, reads, cancellations, released, contract}));
})();
'''.replace('SCENARIO', json.dumps(scenario)).replace('PROJECT', PROJECT).replace('SCRIPT', SCRIPT.read_text())
    result = subprocess.run([node, '-'], input=harness, text=True, encoding='utf-8',
                            capture_output=True, timeout=10, check=True)
    assert 'PRIVATE' not in result.stdout
    receipt = json.loads(result.stdout)
    assert receipt['result'].get('error') == expected
    if scenario in {'wrong_origin', 'missing_auth'}:
        assert receipt['calls'] == 0
    else:
        assert receipt['calls'] == 1 and receipt['contract']
        assert receipt['released'] == 1
        assert receipt['cancellations'] == (0 if scenario == 'complete' else 1)
    if scenario == 'complete':
        assert receipt['reads'] == 3  # both chunks AND observed end-of-stream
        assert receipt['result'] == {'status': 200, 'bytes': 11, 'text': 'hello world'}
    if scenario == 'oversize':
        assert receipt['reads'] == 2 and 'text' not in receipt['result']
