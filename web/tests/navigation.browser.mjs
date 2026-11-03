import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import process from 'node:process';
import { Buffer } from 'node:buffer';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  let role = 'control', status = 200, commands = [], mapRequests = 0, stateRequests = 0;
  let state = { server_age: 0, instance_id: 'one', frame: 'map', mode: 'navigation', csrf: 'csrf', control_owner: null,
    map: { origin: [-5, -5, 0], width: 100, height: 100, resolution: .1, version: 1 },
    robot: [0, 0, Math.PI / 4], scan: [[1, 1], [2, 2]], paths: { plan: [[0, 0], [2, 2]] },
    sensors: { odom: { age: .1, hz: 10 }, scan: { age: .1, hz: 10 } }, readiness: [], values: { enabled: false, control: 0, action: 0 },
    destinations: [{ id: 'lobby', name: '로비', x: 2, y: 2, yaw: 0 }],
  };
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    let data = {};
    if (path === '/api/auth/session') data = { roles: [role] };
    else if (path === '/navigation/api/state') { stateRequests++; return route.fulfill({ status, json: state }); }
    else if (path === '/navigation/api/session') data = { csrf: 'csrf', role: 'admin' };
    else if (path === '/navigation/api/map.png') {
      mapRequests++;
      // A map-sized test PNG from the canvas API; no remote assets.
      const png = await page.evaluate(() => { const c = document.createElement('canvas'); c.width = c.height = 100;
        const x = c.getContext('2d'); x.fillStyle = '#e8e8e8'; x.fillRect(0,0,100,100); x.fillStyle = '#333'; x.fillRect(10,10,80,3); return c.toDataURL().split(',')[1]; });
      return route.fulfill({ contentType: 'image/png', body: Buffer.from(png, 'base64') });
    } else if (path === '/navigation/api/command') {
      data = route.request().postDataJSON(); commands.push(data);
      assert.equal(route.request().headers()['x-dori-control'], 'csrf');
      if (data.action === 'enable') { state.values.enabled = true; state.control_owner = data.client; }
      if (data.action === 'stop') { state.values.enabled = false; state.control_owner = null; }
      if (data.action === 'save_destination') {
        const destination = { ...data, id: data.id || 'new-place' };
        state.destinations = [...state.destinations.filter(g => g.id !== destination.id), destination];
        return route.fulfill({ json: { ok: true, destination } });
      }
      if (data.action === 'delete_destination') state.destinations = state.destinations.filter(g => g.id !== data.id);
      data = { ok: true, message: '명령 처리됨' };
    }
    return route.fulfill({ json: data });
  });
  await page.goto(process.env.NAV_TEST_URL || 'http://127.0.0.1:5178');
  async function openPanel() {
    await page.evaluate(async () => {
      const { useStore } = await import('/src/core/store.js');
      const { PANEL_TREE, findLeaf } = await import('/src/panelTree.jsx');
      useStore.getState().openPanel(findLeaf(PANEL_TREE, 'campus-map'));
    });
    await page.getByText('● 연결됨', { exact: true }).waitFor();
  }
  await openPanel();
  assert.equal(await page.locator('iframe').count(), 0);
  await page.getByRole('button', { name: '초기 위치', exact: true }).click();
  const canvas = page.locator('.nav-viewport canvas');
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width/2, box.y + box.height/2);
  await page.mouse.down(); await page.mouse.move(box.x + box.width/2, box.y + box.height/2 - 50); await page.mouse.up();
  assert.equal(await page.getByLabel('방향 · °', { exact: true }).inputValue(), '90.0');
  await page.getByRole('button', { name: '초기 위치 적용', exact: true }).click();
  await page.waitForTimeout(300);
  assert.equal(commands.find(c => c.action === 'initial_pose').yaw, Math.PI/2);
  await page.getByRole('button', { name: '주행 활성화', exact: true }).click();
  await page.getByText('이 패널이 제어 중', { exact: true }).waitFor();
  await page.getByRole('button', { name: '목표 지정', exact: true }).click();
  await page.getByLabel('X · m', { exact: true }).fill('0');
  await page.getByLabel('Y · m', { exact: true }).fill('2');
  await page.getByLabel('방향 · °', { exact: true }).fill('45');
  await page.getByRole('button', { name: '이 목표로 이동', exact: true }).click();
  await page.waitForTimeout(250);
  assert.equal(commands.find(c => c.action === 'goal').x, 0);
  await page.getByLabel('목표 이름', { exact: true }).fill('시험 지점');
  await page.getByRole('button', { name: '선택 위치 저장', exact: true }).click();
  await page.getByRole('button', { name: '시험 지점', exact: true }).waitFor();
  await page.getByRole('button', { name: '시험 지점', exact: true }).click();
  await page.getByLabel('목표 이름', { exact: true }).fill('수정 지점');
  await page.getByRole('button', { name: '목표 수정 저장', exact: true }).click();
  await page.getByRole('button', { name: '수정 지점', exact: true }).waitFor();
  await page.getByRole('button', { name: '수정 지점 삭제', exact: true }).click();
  await page.waitForTimeout(300);
  assert.equal(state.destinations.length, 1);
  const beforeEscape = commands.filter(c => c.action === 'stop').length;
  await page.locator('body').click({ position: { x: 1400, y: 950 } }); await page.keyboard.press('Escape');
  assert.equal(commands.filter(c => c.action === 'stop').length, beforeEscape);
  await canvas.focus(); await page.keyboard.press('Escape'); await page.waitForTimeout(250);
  assert.equal(commands.filter(c => c.action === 'stop').length, beforeEscape + 1);
  const sameVersion = mapRequests; await page.waitForTimeout(450); assert.equal(mapRequests, sameVersion);
  state.map.version = 2; await page.waitForTimeout(450); assert.equal(mapRequests, sameVersion + 1);
  await page.screenshot({ path: '/tmp/dori-navigation-desktop.png' });
  // Resize actual floating window, then exercise mobile layout.
  await page.evaluate(async () => { const { useStore } = await import('/src/core/store.js'); useStore.getState().resizePanel('campus-map', 600, 650); });
  await page.waitForTimeout(200);
  assert.equal(await page.locator('.nav-layout').evaluate(e => getComputedStyle(e).gridTemplateColumns.split(' ').length), 1);
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(400);
  assert.equal(await page.locator('.nav-layout').evaluate(e => getComputedStyle(e).gridTemplateColumns.split(' ').length), 1);
  assert.ok((await canvas.boundingBox()).width > 200);
  assert.equal(await page.locator('.navigation-panel').evaluate(e => e.scrollWidth <= e.clientWidth + 1), true);
  await page.screenshot({ path: '/tmp/dori-navigation-mobile.png' });
  await page.getByRole('button', { name: '주행 활성화', exact: true }).scrollIntoViewIfNeeded();
  assert.equal(await page.getByRole('button', { name: '주행 활성화', exact: true }).isVisible(), true);
  await page.setViewportSize({ width: 1440, height: 1000 }); await page.waitForTimeout(400);
  state.control_owner = 'other-client'; state.values.enabled = true;
  await page.getByText('다른 브라우저가 제어 중', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: '목표 지정', exact: true }).isDisabled(), true);
  status = 503; await page.getByRole('alert').filter({ hasText: '웹 뷰어' }).waitFor();
  assert.equal(await page.getByRole('button', { name: '초기 위치', exact: true }).isDisabled(), true);
  status = 200; state.instance_id = 'two'; state.control_owner = null; state.values.enabled = false;
  await page.getByText('● 연결됨', { exact: true }).waitFor();
  assert.equal(await page.getByLabel('X · m', { exact: true }).inputValue(), '');
  await page.locator('.fp-btn-minimize').click(); await page.waitForTimeout(300);
  const stoppedRequests = stateRequests, stoppedCommands = commands.length;
  await page.waitForTimeout(500); assert.equal(stateRequests, stoppedRequests); assert.equal(commands.length, stoppedCommands);
  role = 'viewer'; await page.locator('.fp-btn-minimize').click(); await page.getByText('조회 전용', { exact: true }).waitFor();
  assert.equal(await page.getByRole('button', { name: 'AUTO 정지', exact: true }).isDisabled(), true);
  status = 401; await page.getByRole('heading', { name: 'DORI 대시보드 로그인' }).waitFor();
  assert.deepEqual(errors, []);
  console.log('Browser checks passed: selection, commands, destination CRUD, scoped ESC, image caching, resize/mobile, ownership, errors, restart, cleanup, viewer, auth expiry.');
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
