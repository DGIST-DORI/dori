// Run after npm run build. Uses mocked authentication and rosbridge, no robot.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import http from 'node:http';
const { chromium } = await import(process.env.DORI_PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.DORI_DASHBOARD_DIST_ROOT || new URL('../../web/dist', import.meta.url).pathname;
const server = http.createServer(async (req, res) => {
  const path = req.url.split('?')[0];
  res.setHeader('Content-Type', path.endsWith('.js') ? 'text/javascript' : path.endsWith('.css') ? 'text/css' : path.endsWith('.svg') ? 'image/svg+xml' : 'text/html');
  try { res.end(await fs.readFile(root + (path === '/' ? '/index.html' : path))); }
  catch { res.statusCode = 404; res.end(); }
});
await new Promise(resolve => server.listen(5190, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  const context = await browser.newContext({ viewport: { width: 1440, height: 950 }, locale: 'en-US' });
  await context.addInitScript(() => {
    window.dashboardSpeech = [];
    window.speechSynthesis.speak = utterance => {
      window.dashboardSpeech.push(utterance.text);
      queueMicrotask(() => utterance.onend?.({}));
    };
  });
  await context.route('**/api/auth/session', route => route.fulfill({ json: { user: 'test', roles: ['admin'] } }));
  await context.route('**/api/auth/ws-ticket', route => route.fulfill({ json: { ticket: 'test' } }));
  const topics = ['/dori/tts/audio_event', '/dori/tts/speaking', '/dori/tts/done', '/dori/hri/manager_state', '/dori/hri/status',
    '/dori/hri/emotion', '/dori/hri/expression', '/dori/hri/expression_command'];
  const subscribed = new Set();
  let socket;
  await context.routeWebSocket('**/ws/admin?*', ws => {
    subscribed.clear();
    socket = ws;
    ws.onMessage(raw => {
      const message = JSON.parse(raw);
      if (message.op === 'subscribe') subscribed.add(message.topic);
      if (message.op === 'call_service') {
        const values = message.service === '/rosapi/topics'
          ? { topics, types: topics.map(topic => ['/dori/tts/speaking', '/dori/tts/done'].includes(topic) ? 'std_msgs/msg/Bool' : 'std_msgs/msg/String') }
          : { publishers: [], subscribers: [] };
        ws.send(JSON.stringify({ op: 'service_response', service: message.service, id: message.id, result: true, values }));
      }
    });
  });
  const page = await context.newPage(), errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:5190/');
  await page.getByRole('button', { name: 'System', exact: true }).click();
  await page.getByRole('button', { name: 'Event Log', exact: true }).click();
  await page.locator('.hdr-conn button').last().click();
  await page.locator('.hdr-conn button.connected').waitFor();
  const waitForSubscriptions = async () => {
    for (let attempt = 0; !topics.every(topic => subscribed.has(topic)); attempt++) {
      assert.ok(attempt < 100, 'Event Log subscriptions missing');
      await new Promise(resolve => setTimeout(resolve, 50));
    }
  };
  await waitForSubscriptions();
  const publish = (topic, data) => socket.send(JSON.stringify({ op: 'publish', topic, msg: { data } }));
  const remote = { event_type: 'remote_audio', text: '스마트폰 TTS 로그 확인', output: 'phone',
    id: 'test-audio', timestamp: 1, audio_bytes: 42, audio_b64: 'private-audio-payload', playback_mode: 'local_only' };
  publish(topics[1], true);
  publish(topics[0], JSON.stringify(remote));
  const entry = page.locator('.el-entry').filter({ hasText: 'speak: "스마트폰 TTS 로그 확인"' });
  await entry.waitFor();
  assert.equal(await entry.count(), 1);
  assert.equal((await entry.locator('.el-tag').innerText()).trim(), 'TTS');
  await entry.click();
  assert.match(await entry.locator('.el-raw').innerText(), /"output": "phone"/);
  assert.equal((await entry.locator('.el-raw').innerText()).includes('audio_b64'), false);
  assert.deepEqual(await page.evaluate(() => window.dashboardSpeech.filter(text => text.trim())), []);
  publish(topics[0], JSON.stringify({ event_type: 'tts_text', text: '기존 로봇 TTS', playback_mode: 'local_only' }));
  await page.locator('.el-entry').filter({ hasText: 'speak: "기존 로봇 TTS"' }).waitFor();
  publish(topics[1], false);
  publish(topics[2], true);
  await page.locator('.el-entry').filter({ hasText: 'tts_done: true' }).waitFor();

  const manager = data => publish(topics[3], JSON.stringify(data));
  const status = data => publish(topics[4], JSON.stringify(data));
  const emotion = data => publish(topics[5], JSON.stringify(data));
  const expression = data => publish(topics[6], JSON.stringify(data));
  const conditions = { state: 'IDLE', user_visible: false, mic_attached: true, access_blocked: false, tracking_required: false };
  // More samples than the entire log capacity; conversation entries must survive.
  for (let i = 0; i < 400; i++) {
    manager({ state: 'IDLE', state_elapsed_sec: i / 10 });
    status(conditions);
    emotion({ emotion: 'CALM', source: 'state', timestamp: i });
    expression({ expression: 'HAPPY', metrics: { mouth_open: i / 1000 }, timestamp: i });
  }
  status({ ...conditions, access_blocked: true });
  await page.locator('.el-entry').filter({ hasText: 'access_blocked: false → true' }).waitFor();
  assert.equal(await page.locator('.el-entry .tag-STATE').count(), 3);
  assert.equal(await page.locator('.el-entry .tag-EXPR').count(), 2);
  assert.equal(await entry.count(), 1, 'repeated STATE telemetry evicted the TTS event');
  for (const state of ['LISTENING', 'RESPONDING', 'IDLE']) {
    manager({ state, state_elapsed_sec: 0 });
    status({ ...conditions, state, access_blocked: true });
  }
  await page.locator('.el-entry').filter({ hasText: 'RESPONDING → IDLE' }).waitFor();
  assert.equal(await page.locator('.el-entry .tag-STATE').count(), 6);
  for (let i = 0; i < 2; i++) {
    emotion({ emotion: 'HAPPY', timestamp: i });
    expression({ expression: 'NEUTRAL', timestamp: i });
    publish(topics[7], JSON.stringify({ command: 'REPEAT_GUIDANCE' }));
  }
  await page.waitForFunction(() => [...document.querySelectorAll('.el-text')].filter(el => el.textContent.includes('REPEAT_GUIDANCE')).length === 2);
  assert.equal(await page.locator('.el-entry .tag-EXPR').count(), 6, 'expression changes and repeated explicit commands must be retained');
  assert.equal(await page.locator('.el-entry').filter({ hasText: 'emotion: CALM → HAPPY' }).count(), 1);
  assert.equal(await page.locator('.el-entry').filter({ hasText: 'expression: HAPPY → NEUTRAL' }).count(), 1);
  await page.screenshot({ path: '/tmp/dori-dashboard-event-log.png' });

  // Clearing while paused must clear the visible snapshot as well as the buffer.
  await page.getByTitle('Freeze log view (collection continues)').click();
  await page.getByTitle('Clear log', { exact: true }).click();
  assert.equal(await page.locator('.el-entry').count(), 0);
  await page.getByTitle('Freeze log view (collection continues)').click();
  manager({ state: 'IDLE', state_elapsed_sec: 125.5 });
  status({ ...conditions, access_blocked: true });
  emotion({ emotion: 'HAPPY', timestamp: 999 });
  expression({ expression: 'NEUTRAL', timestamp: 999 });
  publish(topics[0], JSON.stringify({ ...remote, text: 'after clear' }));
  await page.locator('.el-entry').filter({ hasText: 'speak: "after clear"' }).waitFor();
  assert.equal(await page.locator('.el-entry .tag-STATE').count(), 0, 'clear must not reset state comparison');
  assert.equal(await page.locator('.el-entry .tag-EXPR').count(), 0, 'clear must not reset expression comparison');

  // Live state timing continues even when no new STATE event is recorded.
  await page.locator('.sb-search-input').fill('State Monitor');
  await page.getByRole('button', { name: 'State Monitor', exact: true }).click();
  await page.waitForFunction(() => document.querySelector('.hri-state-indicator-elapsed')?.textContent === '125.5s');
  assert.equal(await page.locator('.hri-state-indicator-value').innerText(), 'IDLE');

  await page.locator('.hdr-conn button.connected').click();
  await page.locator('.hdr-conn button').last().click();
  await page.locator('.hdr-conn button.connected').waitFor();
  await waitForSubscriptions();
  manager({ state: 'IDLE', state_elapsed_sec: 130 });
  status(conditions);
  emotion({ emotion: 'HAPPY', timestamp: 1000 });
  expression({ expression: 'NEUTRAL', timestamp: 1000 });
  await page.waitForFunction(() => document.querySelectorAll('.el-entry .tag-STATE').length === 2);
  await page.waitForFunction(() => document.querySelectorAll('.el-entry .tag-EXPR').length === 2);

  // A manual palette override must not emit an "ignored" log for every ROS frame.
  await page.locator('.sb-search-input').fill('Emotion Palette');
  await page.getByRole('button', { name: 'Emotion Palette', exact: true }).click();
  await page.getByRole('button', { name: 'Curious', exact: true }).click();
  for (let i = 0; i < 400; i++) {
    manager({ state: 'IDLE', state_elapsed_sec: 130 + i / 10 });
    emotion({ emotion: i % 2 ? 'HAPPY' : 'CALM', timestamp: i });
  }
  publish(topics[0], JSON.stringify({ ...remote, text: 'override telemetry received' }));
  await page.locator('.el-entry').filter({ hasText: 'override telemetry received' }).waitFor({ state: 'attached' });
  assert.equal(await page.locator('.el-entry .tag-EXPR').count(), 3);
  assert.equal(await page.locator('.face-palette-btn.active .face-palette-name').innerText(), 'Curious');
  await page.getByRole('button', { name: 'Clear Override', exact: true }).click();
  emotion({ emotion: 'HAPPY' });
  await page.waitForFunction(() => document.querySelectorAll('.el-entry .tag-EXPR').length === 4);
  assert.deepEqual(errors, []);
  console.log('PASS: phone/local TTS, audio privacy, no duplicate playback, STATE/EXPR change detection, explicit commands, fast transitions, live timing, clear/pause and reconnect.');
} finally {
  await browser.close();
  server.close();
}
