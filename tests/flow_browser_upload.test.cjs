const {test} = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../agent/services/flow_browser_upload.js'), 'utf8');
const project = '10000000-0000-4000-8000-000000000001';
const other = '10000000-0000-4000-8000-000000000002';
function fixture({chunks = [Buffer.from('complete')], moveDuringCaptcha = false} = {}) {
  const calls = [];
  let cancelled = false, released = false;
  const location = {origin: 'https://flow.google.com', pathname: `/project/${project}`};
  const context = {
    location, URL, URLSearchParams, TextDecoder, Uint8Array, AbortController, setTimeout, clearTimeout,
    document: {scripts: [{src: 'https://www.google.com/recaptcha/enterprise.js?render=test-site'}]},
    window: {WIZ_global_data: {SNlM0e: 'test-at', FdrFJe: 'test-session', cfb2h: 'test-build'},
      grecaptcha: {enterprise: {execute: async () => {
        if (moveDuringCaptcha) location.pathname = `/project/${other}`;
        return 'test-captcha-token';
      }}}},
    fetch: async (url, options) => {
      calls.push({url, options});
      const remaining = [...chunks];
      return {status: 200, body: {getReader: () => ({
        read: async () => remaining.length ? {done: false, value: remaining.shift()} : {done: true},
        cancel: async () => { cancelled = true; }, releaseLock: () => { released = true; },
      })}};
    },
  };
  const upload = vm.runInNewContext(`(${source})`, context);
  const inner = [[null, 10, null, null, null, project, null, null, null, null, ['__CAPTCHA__', 1]],
    'aW1hZ2U=', 'image/png', 1, null, null, null, null, '__CAPTCHA__.png', null, project, other];
  const freq = JSON.stringify([[['maseQ', JSON.stringify(inner), null, 'generic']]]);
  return {run: () => upload({projectId: project, freq}), calls,
    get cancelled() { return cancelled; }, get released() { return released; }};
}

test('only the CAPTCHA field changes; user filenames remain literal', async () => {
  const f = fixture({chunks: [Buffer.from('com'), Buffer.from('plete')]});
  const result = await f.run();
  assert.equal(result.data, 'complete');
  assert.equal(result.body_complete, true);
  const envelope = JSON.parse(f.calls[0].options.body.get('f.req'));
  const inner = JSON.parse(envelope[0][0][1]);
  assert.equal(inner[0][10][0], 'test-captcha-token');
  assert.equal(inner[8], '__CAPTCHA__.png');
  assert.equal(f.released, true);
});

test('navigation during CAPTCHA prevents an upload to another project', async () => {
  const f = fixture({moveDuringCaptcha: true});
  const result = await f.run();
  assert.equal(result.error, 'SESSION_UNVERIFIED');
  assert.equal(f.calls.length, 0);
});

test('oversized response cancels and releases instead of claiming full body', async () => {
  const f = fixture({chunks: [new Uint8Array(4 * 1024 * 1024 + 1)]});
  const result = await f.run();
  assert.equal(result.error, 'BODY_BUDGET');
  assert.equal(result.body_complete, undefined);
  assert.equal(f.cancelled, true);
  assert.equal(f.released, true);
});

test('invalid UTF8 is not a completed response', async () => {
  const f = fixture({chunks: [new Uint8Array([0xff])]});
  const result = await f.run();
  assert.equal(result.error, 'UPLOAD_OUTCOME_UNKNOWN');
  assert.equal(f.cancelled, true);
  assert.equal(f.released, true);
});
