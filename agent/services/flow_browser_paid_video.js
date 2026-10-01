async ({ projectId, rpcid, freq, timeoutMs }) => {
  const refuse = (error) => ({ status: 409, error, effect: 'not_submitted' });
  const unknown = (error, status = 502) => ({ status, error, effect: 'unknown' });
  const uuid = /^[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}$/i;
  const allowed = new Set(['eb1hJf', 'YhhmEf', 'nprQif', 'MZZa6b']);

  if (!uuid.test(projectId) || !allowed.has(rpcid) ||
      typeof freq !== 'string' ||
      new TextEncoder().encode(freq).length > 65536 ||
      location.origin !== 'https://flow.google.com' ||
      location.pathname !== `/project/${projectId}`) {
    return refuse('PAID_RECIPE_UNVERIFIED');
  }

  let envelope, inner;
  try {
    envelope = JSON.parse(freq);
    const item = envelope[0][0];
    if (envelope.length !== 1 || envelope[0].length !== 1 ||
        !Array.isArray(item) || item.length !== 4 ||
        item[0] !== rpcid || item[2] !== null || item[3] !== 'generic') {
      return refuse('PAID_RECIPE_UNVERIFIED');
    }
    inner = JSON.parse(item[1]);
    if (!Array.isArray(inner)) return refuse('PAID_RECIPE_UNVERIFIED');
  } catch {
    return refuse('PAID_RECIPE_UNVERIFIED');
  }

  let seenProject = false;
  let captchaSlots = 0;
  const replaceCaptcha = (node, token) => {
    if (!Array.isArray(node)) return;
    if (node.length === 2 && node[0] === '__CAPTCHA__' && node[1] === 1) {
      node[0] = token;
      captchaSlots += 1;
      return;
    }
    for (const item of node) {
      if (item === projectId) seenProject = true;
      replaceCaptcha(item, token);
    }
  };

  const inspect = (node) => {
    if (!Array.isArray(node)) return;
    for (const item of node) {
      if (item === projectId) seenProject = true;
      inspect(item);
    }
  };
  inspect(inner);
  if (!seenProject) return refuse('PAID_RECIPE_UNVERIFIED');

  const wiz = globalThis.WIZ_global_data || {};
  if (!wiz.SNlM0e || !wiz.FdrFJe || !wiz.cfb2h ||
      !window.grecaptcha?.enterprise?.execute) {
    return refuse('SESSION_UNVERIFIED');
  }

  const script = Array.from(document.scripts).find(
    (node) => node.src?.startsWith('https://www.google.com/recaptcha/enterprise.js?')
  );
  const sitekey = script ? new URL(script.src).searchParams.get('render') : null;
  if (!sitekey) return refuse('CAPTCHA_CONFIG_UNVERIFIED');

  let captchaTimer;
  let token;
  try {
    token = await Promise.race([
      window.grecaptcha.enterprise.execute(sitekey, { action: 'VIDEO_GENERATION' }),
      new Promise((_, reject) => {
        captchaTimer = setTimeout(() => reject(Error('captcha_timeout')), 20000);
      }),
    ]);
  } catch {
    return refuse('CAPTCHA_UNAVAILABLE');
  } finally {
    clearTimeout(captchaTimer);
  }
  if (typeof token !== 'string' || !token) return refuse('CAPTCHA_UNAVAILABLE');

  captchaSlots = 0;
  replaceCaptcha(inner, token);
  if (captchaSlots < 1) return refuse('PAID_RECIPE_UNVERIFIED');
  envelope[0][0][1] = JSON.stringify(inner);

  if (location.origin !== 'https://flow.google.com' ||
      location.pathname !== `/project/${projectId}`) {
    return refuse('SESSION_UNVERIFIED');
  }

  const params = new URLSearchParams({
    rpcids: rpcid,
    'source-path': location.pathname,
    bl: wiz.cfb2h,
    'f.sid': wiz.FdrFJe,
    rt: 'c',
    hl: (document.documentElement.lang || navigator.language || 'en').split('-')[0],
    _reqid: String(Math.floor(Math.random() * 900000) + 100000),
  });

  const controller = new AbortController();
  const timer = setTimeout(
    () => controller.abort(),
    Math.max(1000, Math.min(timeoutMs || 120000, 120000)),
  );
  let reader;
  let submitted = false;
  let complete = false;
  try {
    submitted = true;
    const response = await fetch(
      `/_/AiSandboxAngularFrontend/data/batchexecute?${params}`,
      {
        method: 'POST',
        credentials: 'include',
        redirect: 'error',
        signal: controller.signal,
        headers: {
          'content-type': 'application/x-www-form-urlencoded;charset=UTF-8',
          'x-same-domain': '1',
        },
        body: new URLSearchParams({
          'f.req': JSON.stringify(envelope),
          at: wiz.SNlM0e,
        }),
      },
    );
    reader = response.body?.getReader();
    if (response.status !== 200) return unknown('HTTP_REJECTED', response.status);
    if (!reader) return unknown('BODY_INCOMPLETE', response.status);

    const chunks = [];
    let bytes = 0;
    for (;;) {
      const part = await reader.read();
      if (part.done) break;
      bytes += part.value.byteLength;
      if (bytes > 4 * 1024 * 1024) return unknown('BODY_BUDGET', response.status);
      chunks.push(part.value);
    }

    const buffer = new Uint8Array(bytes);
    let offset = 0;
    for (const chunk of chunks) {
      buffer.set(chunk, offset);
      offset += chunk.byteLength;
    }
    const data = new TextDecoder('utf-8', { fatal: true }).decode(buffer);
    complete = true;
    return {
      status: response.status,
      data,
      body_complete: true,
      effect: 'completed',
    };
  } catch {
    return submitted
      ? unknown('PAID_OUTCOME_UNKNOWN')
      : refuse('PAID_NOT_SUBMITTED');
  } finally {
    clearTimeout(timer);
    if (!complete) {
      controller.abort();
      if (reader) {
        try { await reader.cancel(); } catch {}
      }
    }
    if (reader) {
      try { reader.releaseLock(); } catch {}
    }
  }
}
