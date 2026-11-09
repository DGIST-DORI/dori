// Isolated display checks; all requests and session events are mocked. No ROS.
// DORI_DISPLAY_QR_FIXTURE can supply a real SVG QR for visual inspection.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const { chromium } = await import(process.env.DORI_PLAYWRIGHT_MODULE || 'playwright');
const html = await fs.readFile(new URL('../../ros2_ws/src/dori_dashboard/dori_dashboard/display.html', import.meta.url), 'utf8');
const qrImage = process.env.DORI_DISPLAY_QR_FIXTURE
  ? await fs.readFile(process.env.DORI_DISPLAY_QR_FIXTURE)
  : '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><path d="M10 10h30v30H10zM60 10h30v30H60zM10 60h30v30H10zM60 60h30v30H60z"/></svg>';
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, locale: 'ko-KR' });
  const errors = [], pending = new Map(), requests = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    window.EventSource = class extends EventTarget {
      constructor() { super(); window.displayEvents = this; }
    };
  });
  await page.route('**/*', async route => {
    const { pathname } = new URL(route.request().url());
    if (pathname === '/display') return route.fulfill({ contentType: 'text/html', body: html });
    if (pathname.startsWith('/display/qr/')) {
      requests.push(pathname);
      const attempt = requests.filter(path => path === pathname).length;
      if ((pathname.endsWith('/retry-once') && attempt === 1) || pathname.includes('/cancel-retry-')) return route.abort('failed');
      if (pathname.endsWith('/stalled-once') && attempt === 1) { pending.set(pathname, route); return; }
      if (pathname.includes('slow')) { pending.set(pathname, route); return; }
      if (pathname.endsWith('broken')) return route.fulfill({ status: 410, body: 'QR expired' });
      return route.fulfill({ contentType: 'image/svg+xml', body: qrImage, headers: { 'Cache-Control': 'no-store' } });
    }
    throw new Error('Unexpected request: ' + route.request().url());
  });
  await page.clock.install();
  await page.goto('http://display.test/display');
  const emit = (type, data) => page.evaluate(({ type, data }) => {
    window.displayEvents.dispatchEvent(new MessageEvent(type, { data: JSON.stringify(data) }));
  }, { type, data });
  const state = status => emit('state', { status });
  const loadQR = async (nonce = 'ready', ttl = 30) => {
    await state('IDLE');
    await emit('qr_update', { nonce, ttl });
    await page.locator('#qr').waitFor({ state: 'visible' });
    assert.ok(await page.locator('#qr').evaluate(image => image.complete && image.naturalWidth > 0));
  };
  const hiddenQR = async () => assert.equal(await page.locator('#qr').isVisible(), false);
  const waitPending = async nonce => {
    const path = '/display/qr/' + nonce;
    for (let attempt = 0; !pending.has(path); attempt++) {
      assert.ok(attempt < 100, 'Expected pending QR request');
      await new Promise(resolve => setTimeout(resolve, 10));
    }
    return path;
  };
  const release = async nonce => {
    const path = await waitPending(nonce);
    const response = page.waitForResponse(response => new URL(response.url()).pathname === path);
    await pending.get(path).fulfill({ contentType: 'image/svg+xml', body: qrImage });
    await (await response).finished();
    await page.waitForTimeout(50);
  };

  await hiddenQR();
  await loadQR();
  assert.equal(requests.filter(path => path.endsWith('/ready')).length, 1, 'Display must reuse the preloaded no-store image');
  assert.equal(await page.locator('#steps').isVisible(), true);
  assert.equal(await page.getByRole('img', { name: 'DORI', exact: true }).count(), 1);
  const fontSizes = await page.evaluate(() => ['#status', '.greeting'].map(selector => parseFloat(getComputedStyle(document.querySelector(selector)).fontSize)));
  assert.ok(fontSizes[0] > fontSizes[1] * 2, 'Connection status must dominate the greeting');
  await page.screenshot({ path: '/tmp/dori-display-idle.png' });

  for (const [status, heading, tone] of [
    ['ACTIVE', '지금은 방문자와\n대화하고 있어요', 'green'],
    ['GRACE', '스마트폰 연결을\n기다리고 있어요', 'amber'],
    ['ENDING', '다음 만남을\n준비하고 있어요', 'blue'],
  ]) {
    await (status === 'ACTIVE' ? emit('paired', { status }) : state(status));
    await hiddenQR();
    assert.equal(await page.locator('#status').innerText(), heading);
    assert.equal(await page.locator('body').getAttribute('data-tone'), tone);
    assert.equal(await page.locator('#steps').isVisible(), false);
    await emit('qr_update', { nonce: 'ignored', ttl: 30 });
    await hiddenQR();
    await page.screenshot({ path: `/tmp/dori-display-${status.toLowerCase()}.png` });
  }
  assert.equal(requests.some(path => path.endsWith('/ignored')), false);

  // Image failure, QR expiry, reconnect, and delayed responses must not leave
  // an unusable code on screen or overwrite the current session state.
  await state('IDLE');
  await emit('qr_update', { nonce: 'broken', ttl: 30 });
  await page.waitForTimeout(50);
  await hiddenQR();
  assert.match(await page.locator('#status').innerText(), /새 QR/);

  // A failed first request must recover without waiting for the next SSE QR
  // rotation. Slow requests also need a bound before trying again.
  const failQR = async (nonce, ttl = 30) => {
    await state('IDLE');
    const failed = page.waitForEvent('requestfailed', request => new URL(request.url()).pathname.endsWith('/' + nonce));
    await emit('qr_update', { nonce, ttl });
    await failed;
    await page.waitForTimeout(50);
    await hiddenQR();
  };
  await failQR('retry-once');
  await page.clock.fastForward(1000);
  await page.locator('#qr').waitFor({ state: 'visible', timeout: 3000 });
  assert.equal(requests.filter(path => path.endsWith('/retry-once')).length, 2);

  await state('IDLE');
  await emit('qr_update', { nonce: 'stalled-once', ttl: 30 });
  await waitPending('stalled-once');
  await page.clock.fastForward(5000);
  await hiddenQR();
  await page.clock.fastForward(1000);
  await page.locator('#qr').waitFor({ state: 'visible', timeout: 3000 });
  assert.equal(requests.filter(path => path.endsWith('/stalled-once')).length, 2);
  await pending.get('/display/qr/stalled-once').fulfill({ contentType: 'image/svg+xml', body: qrImage });

  for (const action of ['paired', 'offline', 'expired', 'newer']) {
    const nonce = 'cancel-retry-' + action;
    await failQR(nonce, action === 'expired' ? 0.5 : 30);
    if (action === 'paired') await emit('paired', { status: 'ACTIVE' });
    if (action === 'offline') await page.evaluate(() => window.displayEvents.onerror());
    if (action === 'newer') await loadQR('after-retry-cancel');
    await page.clock.fastForward(1500);
    assert.equal(requests.filter(path => path.endsWith('/' + nonce)).length, 1, 'Obsolete QR retries must be cancelled');
    if (action === 'newer') assert.ok((await page.locator('#qr').getAttribute('src')).endsWith('/after-retry-cancel'));
    else await hiddenQR();
  }

  await loadQR('expiring', 2);
  await page.clock.fastForward(2100);
  await hiddenQR();
  await loadQR('before-disconnect');
  await page.evaluate(() => window.displayEvents.onerror());
  await hiddenQR();
  await emit('qr_update', { nonce: 'offline-ignored', ttl: 30 });
  await hiddenQR();
  await page.screenshot({ path: '/tmp/dori-display-offline.png' });

  for (const action of ['paired', 'offline', 'expired', 'newer']) {
    await state('IDLE');
    await emit('qr_update', { nonce: 'slow-' + action, ttl: 2 });
    if (action === 'paired') await emit('paired', { status: 'ACTIVE' });
    if (action === 'offline') await page.evaluate(() => window.displayEvents.onerror());
    if (action === 'expired') await page.clock.fastForward(2100);
    if (action === 'newer') await loadQR('replacement');
    const heading = await page.locator('#status').innerText();
    await release('slow-' + action);
    assert.equal(await page.locator('#status').innerText(), heading, 'Late QR must not overwrite the latest state');
    if (action === 'newer') assert.ok((await page.locator('#qr').getAttribute('src')).endsWith('/replacement'));
    else await hiddenQR();
  }
  await state('UNKNOWN');
  await hiddenQR();
  await loadQR('recovered', 300);

  for (const [width, height] of [[1920, 1080], [1280, 800], [1024, 600], [800, 480], [600, 960], [390, 844]]) {
    await page.setViewportSize({ width, height });
    const metrics = await page.evaluate(() => {
      const qr = document.getElementById('qr').getBoundingClientRect();
      return {
        width: document.documentElement.scrollWidth, height: document.documentElement.scrollHeight,
        qrWidth: qr.width, qrHeight: qr.height,
      };
    });
    await page.screenshot({ path: `/tmp/dori-display-${width}x${height}.png`, fullPage: true });
    assert.ok(metrics.width <= width, `No horizontal overflow at ${width}x${height}`);
    if (width >= 800) assert.ok(metrics.height <= height, `Kiosk must fit at ${width}x${height}: ${JSON.stringify(metrics)}`);
    assert.ok(Math.abs(metrics.qrWidth - metrics.qrHeight) < 1, 'QR must stay square');
    assert.ok(metrics.qrWidth >= 220, 'QR must remain large enough to scan');
  }
  assert.deepEqual(errors, []);
  console.log('Display checks passed: state transitions, QR loading/retries/timeouts/expiry/races, logo, and six viewport sizes.');
} finally {
  await browser.close();
}
