import { useCallback, useEffect, useRef, useState } from 'react';
import { createHardwareClient } from './client.js';

export function useHardware() {
  const client = useRef(null);
  const [snapshot, setSnapshot] = useState({ state: null, online: false, holding: false, busy: false, error: '', notice: '' });
  useEffect(() => {
    const connection = createHardwareClient(setSnapshot);
    client.current = connection;
    const release = () => void connection.stop();
    const visibility = () => { if (document.hidden) release(); };
    window.addEventListener('blur', release);
    window.addEventListener('pagehide', release);
    document.addEventListener('visibilitychange', visibility);
    connection.start();
    return () => {
      window.removeEventListener('blur', release);
      window.removeEventListener('pagehide', release);
      document.removeEventListener('visibilitychange', visibility);
      connection.dispose(); client.current = null;
    };
  }, []);
  const command = useCallback((action, params) => client.current?.command(action, params), []);
  const hold = useCallback(params => client.current?.hold(params), []);
  const release = useCallback(() => client.current?.stop(), []);
  return { ...snapshot, command, hold, release };
}
