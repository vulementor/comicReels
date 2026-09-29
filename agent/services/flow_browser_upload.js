async ({projectId, freq}) => {
  const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/;
  if (!uuid.test(projectId) || location.origin !== 'https://flow.google.com' ||
      location.pathname !== `/project/${projectId}` || typeof freq !== 'string' ||
      freq.length > 12 * 1024 * 1024) return {error: 'UPLOAD_INPUT_INVALID'};
  let envelope, inner;
  try {
    envelope = JSON.parse(freq);
    const item = envelope[0][0];
    inner = JSON.parse(item[1]);
    if (envelope.length !== 1 || envelope[0].length !== 1 || item.length !== 4 ||
        item[0] !== 'maseQ' || item[2] !== null || item[3] !== 'generic' ||
        inner.length !== 12 || inner[0][5] !== projectId ||
        inner[0][10][0] !== '__CAPTCHA__' || inner[0][10][1] !== 1)
      return {error: 'UPLOAD_INPUT_INVALID'};
  } catch { return {error: 'UPLOAD_INPUT_INVALID'}; }
  const wiz = window.WIZ_global_data || {};
  if (!wiz.SNlM0e || !wiz.FdrFJe || !wiz.cfb2h || !window.grecaptcha?.enterprise?.execute)
    return {error: 'SESSION_UNVERIFIED'};
  const script = Array.from(document.scripts).find(s => s.src.startsWith('https://www.google.com/recaptcha/enterprise.js?'));
  const sitekey = script && new URL(script.src).searchParams.get('render');
  if (!sitekey) return {error: 'CAPTCHA_CONFIG_UNVERIFIED'};
  let token, captchaTimer;
  try {
    token = await Promise.race([
      window.grecaptcha.enterprise.execute(sitekey, {action: 'IMAGE_GENERATION'}),
      new Promise((_, reject) => { captchaTimer = setTimeout(() => reject(Error('timeout')), 20000); })
    ]);
  } catch { return {error: 'CAPTCHA_UNAVAILABLE'}; }
  finally { clearTimeout(captchaTimer); }
  if (typeof token !== 'string' || !token) return {error: 'CAPTCHA_UNAVAILABLE'};
  if (location.origin !== 'https://flow.google.com' || location.pathname !== `/project/${projectId}`)
    return {error: 'SESSION_UNVERIFIED'};
  inner[0][10][0] = token;
  envelope[0][0][1] = JSON.stringify(inner);
  const params = new URLSearchParams({rpcids: 'maseQ', 'source-path': location.pathname,
    bl: wiz.cfb2h, 'f.sid': wiz.FdrFJe, rt: 'c', hl: 'vi',
    _reqid: String(Math.floor(Math.random() * 900000) + 100000)});
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60000);
  let reader, complete = false;
  try {
    const response = await fetch(`/_/AiSandboxAngularFrontend/data/batchexecute?${params}`, {
      method: 'POST', credentials: 'include', redirect: 'error', signal: controller.signal,
      headers: {'content-type': 'application/x-www-form-urlencoded;charset=UTF-8', 'x-same-domain': '1'},
      body: new URLSearchParams({'f.req': JSON.stringify(envelope), at: wiz.SNlM0e})
    });
    reader = response.body?.getReader();
    if (!reader) return {error: 'BODY_INCOMPLETE'};
    const chunks = [];
    let bytes = 0;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > 4 * 1024 * 1024) return {error: 'BODY_BUDGET'};
      chunks.push(part.value);
    }
    const buffer = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) { buffer.set(chunk, offset); offset += chunk.byteLength; }
    const data = new TextDecoder('utf-8', {fatal: true}).decode(buffer);
    complete = true;
    return {status: response.status, data, body_complete: true};
  } catch { return {error: 'UPLOAD_OUTCOME_UNKNOWN'}; }
  finally {
    clearTimeout(timer);
    if (!complete) {
      controller.abort();
      if (reader) { try { await reader.cancel(); } catch {} }
    }
    if (reader) { try { reader.releaseLock(); } catch {} }
  }
}
