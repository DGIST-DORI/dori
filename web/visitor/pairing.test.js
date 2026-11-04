import test from 'node:test';
import assert from 'node:assert/strict';
import { confirmPairingScan, pairingError } from './pairing.js';

test('scanning exchanges the nonce before consent; reload uses the cookie', async () => {
  const requests = [];
  const fetchMock = async (url, options) => {
    requests.push({ url, options });
    return { ok: true, json: async () => ({ expires_in: 120 }) };
  };
  assert.equal((await confirmPairingScan('qr-proof', fetchMock)).expires_in, 120);
  assert.deepEqual(JSON.parse(requests[0].options.body), { nonce: 'qr-proof' });
  assert.equal(requests[0].url, '/api/pair/claim');
  await confirmPairingScan('', fetchMock);
  assert.equal(requests[1].options.body, undefined);
  assert.equal(requests[1].options.cache, 'no-store');
});

test('unavailable robot and expired proof have distinct recovery messages', async () => {
  assert.match(pairingError(503), /음성 서비스/);
  assert.doesNotMatch(pairingError(503), /지났습니다|만료/);
  await assert.rejects(confirmPairingScan('old', async () => ({ ok: false, status: 410 })),
    error => error.status === 410 && /새 코드/.test(error.message));
});
