import { useEffect, useRef, useState, useCallback } from 'react';
import { createNavigationClient } from './client.js';

export function useNavigation() {
  const client = useRef(null);
  const [snapshot, setSnapshot] = useState({ state: null, online: false, canControl: false, error: '', clientId: '' });
  useEffect(() => {
    const connection = createNavigationClient(setSnapshot);
    client.current = connection;
    connection.start();
    return () => { connection.dispose(); client.current = null; };
  }, []);
  const command = useCallback((action, extra) => client.current
    ? client.current.command(action, extra) : Promise.reject(new Error('연결을 기다리세요.')), []);
  return { ...snapshot, command };
}
