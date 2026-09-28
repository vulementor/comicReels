async ({ rpcid, freq, projectId, match, timeoutMs }) => {
  const allowed = new Set(['jHPbke', 'Zzl0ze', 'as29s', 'jwpduf']);
  const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
  const refuse = (error) => ({ status: 409, error, effect: 'not_submitted' });
  if (!allowed.has(rpcid) || typeof freq !== 'string' || new TextEncoder().encode(freq).length > 16384)
    return refuse('RPC_NOT_ALLOWED');
  try {
    const envelope = JSON.parse(freq);
    if (envelope.length !== 1 || envelope[0].length !== 1 || envelope[0][0].length !== 4 ||
        envelope[0][0][0] !== rpcid || envelope[0][0][2] !== null || envelope[0][0][3] !== 'generic')
      return refuse('RECIPE_UNVERIFIED');
  } catch { return refuse('RECIPE_UNVERIFIED'); }
  if (location.origin !== 'https://flow.google.com' ||
      (projectId && (!uuid.test(projectId) || location.pathname !== `/project/${projectId}`)) ||
      (match && (rpcid !== 'Zzl0ze' || !uuid.test(match)))) return refuse('SESSION_UNVERIFIED');
  const wiz = globalThis.WIZ_global_data || {};
  if (!wiz.SNlM0e || !wiz.FdrFJe || !wiz.cfb2h) return refuse('SESSION_UNVERIFIED');
  const params = new URLSearchParams({ rpcids: rpcid, 'source-path': location.pathname,
    bl: wiz.cfb2h, 'f.sid': wiz.FdrFJe, rt: 'c',
    hl: (document.documentElement.lang || navigator.language || 'en').split('-')[0],
    _reqid: String(Math.floor(Math.random() * 900000) + 100000),
  });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), Math.max(1000, Math.min(timeoutMs || 15000, 120000)));
  let reader, status, complete = false;
  try {
    const response = await fetch(`/_/AiSandboxAngularFrontend/data/batchexecute?${params}`, {
      method: 'POST', credentials: 'include', redirect: 'error', signal: controller.signal,
      headers: { 'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'x-same-domain': '1' },
      body: new URLSearchParams({ 'f.req': freq, at: wiz.SNlM0e }),
    });
    status = response.status;
    reader = response.body?.getReader();
    if (status !== 200) return { status, error: 'HTTP_REJECTED', effect: 'unknown' };
    if (!reader) return { status, error: 'BODY_INCOMPLETE', effect: 'unknown' };
    const chunks = [];
    let bytes = 0;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      // Existing project listings exceed 17 MiB. Bound the whole response, never silently truncate.
      if (bytes > 32 * 1024 * 1024) return { status, error: 'BODY_BUDGET', effect: 'unknown' };
      chunks.push(part.value);
    }
    const buffer = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.byteLength; }
    const text = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
    complete = true;
    const found = match ? text.indexOf(match) : -1;
    return { status, data: match ? (found < 0 ? '' : text.slice(found, found + 800)) : text,
      response_bytes: bytes, body_complete: true, effect: 'completed' };
  } catch {
    return { status: status || 502, error: 'BODY_INCOMPLETE', effect: 'unknown' };
  } finally {
    clearTimeout(timer);
    if (!complete) {
      controller.abort();
      if (reader) { try { await reader.cancel(); } catch {} }
    }
    if (reader) { try { reader.releaseLock(); } catch {} }
  }
}
