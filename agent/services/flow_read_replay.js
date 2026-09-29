async ({ projectId }) => {
  // Flow-specific, non-paid, observed Zzl0ze shape only. No caller-supplied RPC or URL.
  const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
  if (!uuid.test(projectId) || location.origin !== 'https://flow.google.com' ||
      location.pathname !== `/project/${projectId}`) {
    return { error: 'SESSION_UNVERIFIED' };
  }
  const wiz = globalThis.WIZ_global_data || {};
  if (!wiz.SNlM0e || !wiz.FdrFJe || !wiz.cfb2h) return { error: 'SESSION_UNVERIFIED' };
  const params = new URLSearchParams({
    rpcids: 'Zzl0ze', 'source-path': location.pathname, bl: wiz.cfb2h,
    'f.sid': wiz.FdrFJe,
    hl: (document.documentElement.lang || navigator.language || 'en').split('-')[0],
    _reqid: String(Math.floor(Math.random() * 900000) + 100000), rt: 'c',
  });
  const freq = JSON.stringify([[['Zzl0ze',
    JSON.stringify([`projects/${projectId}`, null, null, null, [1]]), null, 'generic']]]);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  let reader;
  let status;
  let complete = false;
  try {
    const response = await fetch(`/_/AiSandboxAngularFrontend/data/batchexecute?${params}`, {
      method: 'POST', credentials: 'include', redirect: 'error', signal: controller.signal,
      headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'x-same-domain': '1' },
      body: new URLSearchParams({ 'f.req': freq, at: wiz.SNlM0e }),
    });
    status = response.status;
    reader = response.body?.getReader();
    if (status !== 200) return { status, error: 'HTTP_REJECTED' };
    if (!reader) return { status, error: 'BODY_INCOMPLETE' };
    const chunks = [];
    let bytes = 0;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > 512 * 1024) return { status, error: 'BODY_BUDGET' };
      chunks.push(part.value);
    }
    const buffer = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.byteLength; }
    const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
    complete = true;
    // No auth fields cross the bridge. The response is transient; Python projects structure only.
    return { status, bytes, text };
  } catch {
    return { status, error: 'BODY_INCOMPLETE' };
  } finally {
    clearTimeout(timer);
    if (!complete) {
      controller.abort();
      if (reader) { try { await reader.cancel(); } catch {} }
    }
    if (reader) { try { reader.releaseLock(); } catch {} }
  }
}
