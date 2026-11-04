export function pairingError(status) {
  return ({
    409: '다른 방문자가 사용 중이거나 로봇이 정리 중입니다. 잠시 후 새 QR을 스캔해 주세요.',
    410: '연결 확인 시간이 지났습니다. QR 화면의 새 코드를 스캔해 주세요.',
    429: '연결 시도가 많습니다. 1분 후 다시 시도해 주세요.',
    503: '로봇의 음성 서비스가 아직 준비되지 않았습니다. 운영자에게 알려 주세요. 확인 시간이 남아 있으면 다시 시도할 수 있습니다.',
  })[status] || '연결할 수 없습니다. 네트워크를 확인하고 다시 시도해 주세요.';
}

export async function confirmPairingScan(nonce, fetchRequest = fetch) {
  const response = await fetchRequest('/api/pair/claim', nonce ? {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ nonce }),
  } : { cache: 'no-store' });
  if (!response.ok) {
    const error = new Error(pairingError(response.status));
    error.status = response.status;
    throw error;
  }
  return response.json();
}
