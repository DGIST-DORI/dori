import { useEffect, useState } from 'react';
import { apiFetch, loginWithToken } from '../core/api';
import { disconnectROS } from '../core/ros';
import { useStore } from '../core/store';
import './AuthGate.css';

export default function AuthGate({ children }) {
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [token, setToken] = useState('');
  const [kind, setKind] = useState('jwt');
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const requireLogin = () => {
      disconnectROS();
      useStore.getState().setConnected(false);
      setAuthenticated(false);
    };
    window.addEventListener('dori-auth-required', requireLogin);
    const checkSession = () => apiFetch('/api/auth/session').then(response => {
      if (!cancelled) setAuthenticated(response.ok);
    }).catch(() => {
      if (!cancelled) setError('서버에 연결할 수 없습니다. 접속 주소와 Access 로그인을 확인하세요.');
    }).finally(() => {
      if (!cancelled) setChecking(false);
    });
    checkSession();
    const timer = window.setInterval(checkSession, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener('dori-auth-required', requireLogin);
    };
  }, []);

  async function login(event) {
    event.preventDefault();
    setChecking(true);
    setError('');
    try {
      await loginWithToken(token, kind);
      setToken('');
      setAuthenticated(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setChecking(false);
    }
  }

  if (authenticated) return children;
  return <main className="auth-gate">
    <form className="auth-card" onSubmit={login}>
      <h1>DORI 대시보드 로그인</h1>
      <p>운영 계정으로 Cloudflare Access에 로그인하거나 발급받은 토큰을 입력하세요.</p>
      <a href="/">Cloudflare Access 로그인 / 다시 확인</a>
      <label>토큰 종류
        <select value={kind} onChange={event => setKind(event.target.value)}>
          <option value="jwt">만료 시간이 있는 JWT</option>
          <option value="access">비상용 Access 토큰</option>
        </select>
      </label>
      <label>토큰
        <input type="password" autoComplete="off" required value={token}
          onChange={event => setToken(event.target.value)} />
      </label>
      <p>토큰은 브라우저 저장소에 저장하지 않습니다. 비상용 토큰은 서버에서 허용한 경우만 사용할 수 있습니다.</p>
      {error && <p role="alert">{error}</p>}
      <button type="submit" disabled={checking}>{checking ? '확인 중…' : '로그인'}</button>
    </form>
  </main>;
}
