import { createRequire } from 'node:module';
import assert from 'node:assert/strict';
import process from 'node:process';
const require = createRequire(import.meta.url);
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const browser = await chromium.launch({ headless: true, args: ['--no-sandbox'] });
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1080 }, locale: 'ko-KR' });
  const errors = [], commands = [];
  let polls = 0, fail = false;
  let state = { executor: 'dry-run', live_enabled: false, can_control: true, supervisor_available: true, mode: 0, action_state: 0,
    control_epoch: 'a'.repeat(32), stop_latched: false, transform_available: true, move_owner: null,
    joints: ['left_wheel_joint', 'right_wheel_joint', 'motor_3_joint', 'motor_4_joint', 'motor_5_joint'].map((name, i) => ({
      name, label: ['왼쪽 바퀴 · M1', '오른쪽 바퀴 · M2', '몸체 서보 · M3', '변형 서보 · M4', '서보 · M5'][i],
      fresh: true, age: .02, position: i * .1, velocity: 0, effort: i < 2 ? .2 : null,
    })), values: { 'body/pitch': { value: .02, age: .1 } }, feedback: {},
  };
  page.on('pageerror', e => errors.push(e.message));
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    if (path === '/api/auth/session') return route.fulfill({ json: { roles: [state.can_control ? 'operator' : 'viewer'] } });
    if (path === '/api/control/state') {
      polls++;
      return route.fulfill({ status: fail ? 503 : 200, json: fail ? { detail: 'test disconnect' } : state });
    }
    if (path === '/api/control/actions') {
      const body = route.request().postDataJSON(); commands.push(body);
      if (body.action === 'set_live_control') {
        state.live_enabled = body.params.enabled; state.executor = state.live_enabled ? 'bridge' : 'dry-run';
        state.stop_latched = true; state.action_state = 4;
        state.control_epoch = String(commands.length).padStart(32, '0');
        return route.fulfill({ json: { ok: true, executed: true, control_state: state } });
      }
      if (body.action === 'stop') { state.stop_latched = true; state.action_state = 4; }
      if (body.action === 'resume') { state.stop_latched = false; state.action_state = 0; }
      if (body.action === 'set_mode') state.mode = body.params.mode === 'manual' ? 0 : 1;
      return route.fulfill({ json: { ok: true, executed: state.live_enabled } });
    }
    return route.fulfill({ json: {} });
  });
  await page.goto(process.env.HARDWARE_TEST_URL || 'http://127.0.0.1:5179');
  await page.evaluate(async () => {
    const { useStore } = await import('/src/core/store.js');
    const { PANEL_TREE, findLeaf } = await import('/src/panelTree.jsx');
    useStore.getState().openPanel(findLeaf(PANEL_TREE, 'hardware-control'));
  });
  await page.getByText('제어기 연결됨', { exact: true }).waitFor();
  assert.equal(commands.length, 0);
  const forward = page.getByRole('button', { name: '전진', exact: true });
  await page.getByRole('button', { name: '실제 제어 켜기', exact: true }).click();
  await page.getByRole('button', { name: '실제 제어 끄기', exact: true }).waitFor();
  assert.equal(await forward.isDisabled(), true);
  assert.equal(commands.at(-1).action, 'set_live_control');
  assert.equal(commands.at(-1).params.enabled, true);
  await page.getByRole('button', { name: '정지 해제 / 변형 재개', exact: true }).click(); await page.waitForTimeout(350);
  const rect = await forward.boundingBox();
  await page.mouse.move(rect.x + rect.width / 2, rect.y + rect.height / 2);
  await page.mouse.down(); await page.waitForTimeout(300);
  assert.ok(commands.filter(c => c.action === 'move').length >= 2);
  await page.mouse.move(1300, 900); await page.mouse.up(); await page.waitForTimeout(300);
  assert.equal(commands.at(-1).action, 'stop'); assert.equal(await forward.isDisabled(), true);
  await page.getByRole('button', { name: '정지 해제 / 변형 재개', exact: true }).click();
  await page.waitForTimeout(350);
  await forward.focus(); await page.keyboard.down('Space'); await page.waitForTimeout(200); await page.keyboard.up('Space');
  await page.waitForTimeout(200); assert.equal(commands.at(-1).action, 'stop');
  await page.getByRole('button', { name: '정지 해제 / 변형 재개', exact: true }).click(); await page.waitForTimeout(350);
  await page.getByRole('button', { name: 'B B 자세로 변형', exact: true }).click();
  assert.ok(commands.some(c => c.action === 'transform' && c.params.pose === 'B'));
  await page.screenshot({ path: '/tmp/dori-hardware-desktop.png' });
  await forward.focus(); await page.keyboard.down('Space'); await page.waitForTimeout(150);
  await page.evaluate(() => window.dispatchEvent(new Event('blur'))); await page.keyboard.up('Space');
  await page.waitForTimeout(250); assert.equal(commands.at(-1).action, 'stop');
  state.stop_latched = false; state.action_state = 0;
  await page.waitForTimeout(300);
  fail = true; await page.getByRole('alert').filter({ hasText: 'test disconnect' }).waitFor();
  assert.equal(await forward.isDisabled(), true);
  assert.equal(await page.getByRole('button', { name: /비상 정지/ }).isDisabled(), false);
  assert.equal(await page.getByRole('button', { name: '실제 제어 끄기', exact: true }).isDisabled(), false);
  await page.getByRole('button', { name: '실제 제어 끄기', exact: true }).click();
  await page.getByRole('button', { name: '실제 제어 켜기', exact: true }).waitFor();
  assert.equal(commands.at(-1).params.enabled, false);
  fail = false; state.can_control = false; await page.waitForTimeout(400);
  assert.equal(await forward.isDisabled(), true);
  assert.equal(await page.getByRole('button', { name: /비상 정지/ }).isDisabled(), true);
  assert.equal(await page.getByRole('button', { name: '실제 제어 켜기', exact: true }).isDisabled(), true);
  state.can_control = true; state.live_enabled = false; state.executor = 'dry-run'; await page.waitForTimeout(400);
  await page.getByText('모의 제어: 명령을 검증하며 실제 로봇은 움직이지 않습니다.').waitFor();
  await page.getByRole('button', { name: 'B B 자세로 변형', exact: true }).click();
  await page.getByRole('status').filter({ hasText: '로봇은 움직이지 않습니다' }).waitFor();
  state.manual_input_conflict = true; await page.waitForTimeout(350);
  assert.equal(await page.getByRole('button', { name: '실제 제어 켜기', exact: true }).isDisabled(), true);
  await page.getByText('조이스틱 또는 키보드 입력을 종료한 뒤 실제 제어를 켜세요.').waitFor();
  state.manual_input_conflict = false; await page.waitForTimeout(350);
  assert.equal(await page.getByRole('button', { name: '실제 제어 켜기', exact: true }).isDisabled(), false);
  await page.setViewportSize({ width: 390, height: 844 }); await page.waitForTimeout(400);
  assert.equal(await page.locator('.hw-layout').evaluate(e => getComputedStyle(e).gridTemplateColumns.split(' ').length), 1);
  assert.equal(await page.locator('.hardware-panel').evaluate(e => e.scrollWidth <= e.clientWidth + 1), true);
  await page.screenshot({ path: '/tmp/dori-hardware-mobile.png' });
  await page.setViewportSize({ width: 1440, height: 1080 }); await page.waitForTimeout(300);
  await page.locator('.fp-btn-minimize').click(); await page.waitForTimeout(300);
  const before = polls; await page.waitForTimeout(600); assert.equal(polls, before);
  assert.deepEqual(errors, []);
  console.log('Hardware browser checks passed: runtime live/simulation switch, latched transitions, conflicts, no startup motion, hold/release, keyboard, blur, resume, posture, disconnect, roles, mobile, cleanup.');
} finally { await browser.close(); }
