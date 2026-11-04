import { useEffect, useState } from 'react';
import { getAuthSession, loginWithToken } from '../core/api';
import { disconnectROS } from '../core/ros';
import { useStore } from '../core/store';
import { useI18n } from '../core/i18n';
import Logo from '../assets/logo/logo-icon-color.svg?react';
import './AuthGate.css';

export default function AuthGate({ children }) {
  const { t, effectiveLang, langPref } = useI18n();
  const setLangPref = useStore(state => state.setLangPref);
  const [authenticated, setAuthenticated] = useState(false);
  const [checking, setChecking] = useState(true);
  const [signingIn, setSigningIn] = useState(false);
  const [token, setToken] = useState('');
  const [kind, setKind] = useState('jwt');
  const [error, setError] = useState('');

  useEffect(() => {
    document.documentElement.lang = effectiveLang;
  }, [effectiveLang]);

  useEffect(() => {
    let cancelled = false;
    const requireLogin = () => {
      disconnectROS();
      useStore.getState().setConnected(false);
      setAuthenticated(false);
    };
    window.addEventListener('dori-auth-required', requireLogin);
    const checkSession = () => getAuthSession().then(session => {
      if (!cancelled) {
        setAuthenticated(Boolean(session));
        setError('');
      }
    }).catch(error => {
      if (!cancelled) {
        setAuthenticated(false);
        setError(error.code || 'auth.error.unknown');
      }
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
    setSigningIn(true);
    setError('');
    try {
      await loginWithToken(token, kind);
      setToken('');
      setAuthenticated(true);
    } catch (err) {
      setError(err.code || 'auth.error.unknown');
    } finally {
      setSigningIn(false);
    }
  }

  if (authenticated) return children;
  return <main className="auth-gate" lang={effectiveLang}>
    <section className="auth-card" aria-labelledby="auth-title">
      <label className="auth-language">{t('auth.language')}
        <select value={langPref} onChange={event => setLangPref(event.target.value)}>
          <option value="auto">{t('settings.lang.auto')}</option>
          <option value="ko">한국어</option>
          <option value="en">English</option>
        </select>
      </label>
      <div className="auth-intro">
        <Logo className="auth-logo" aria-hidden="true" />
        <h1 id="auth-title">{t('auth.title')}</h1>
        <p>{t('auth.description')}</p>
      </div>
      <div className="auth-primary">
        <a className="auth-email" href="/">{t('auth.email')}<span aria-hidden="true">→</span></a>
        <p className="auth-provider">{t('auth.provider')}</p>
      </div>
      {checking && <p className="auth-status" role="status">{t('auth.checking')}</p>}
      {error && <p className="auth-error" role="alert">{t(error)}</p>}
      <details className="auth-alternative">
        <summary>{t('auth.otherOptions')}</summary>
        <form className="auth-token-form" onSubmit={login}>
          <p>{t('auth.tokenHelp')}</p>
          <label>{t('auth.tokenKind')}
            <select value={kind} onChange={event => setKind(event.target.value)} disabled={signingIn}>
              <option value="jwt">{t('auth.jwt')}</option>
              <option value="access">{t('auth.emergency')}</option>
            </select>
          </label>
          <label>{t('auth.token')}
            <input type="password" autoComplete="off" required value={token} disabled={signingIn}
              spellCheck={false} autoCapitalize="none" onChange={event => setToken(event.target.value)} />
          </label>
          <button type="submit" disabled={checking || signingIn}>
            {t(signingIn ? 'auth.signingIn' : 'auth.tokenSubmit')}
          </button>
        </form>
      </details>
    </section>
  </main>;
}
