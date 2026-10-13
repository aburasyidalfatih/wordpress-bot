import { useEffect, useState } from 'react';
import { apiFetch, isAbortError } from '@/lib/api';
import type { UserProfile } from '@/lib/types';

/**
 * Profile of the signed-in user (name, role, credits...). Refetched whenever a
 * `refresh-profile` window event is dispatched, e.g. after credits change.
 */
export function useProfile() {
  const [profile, setProfile] = useState<UserProfile>({});

  useEffect(() => {
    const controller = new AbortController();
    const load = (signal?: AbortSignal) =>
      apiFetch('/api/profile', { signal })
        .then(res => res.json())
        .then(data => {
          if (data.success && data.profile) setProfile(data.profile);
        })
        .catch(err => {
          if (!isAbortError(err) && import.meta.env.DEV) console.error(err);
        });

    load(controller.signal);
    const handleRefresh = () => { load(); };
    window.addEventListener('refresh-profile', handleRefresh);
    return () => {
      controller.abort();
      window.removeEventListener('refresh-profile', handleRefresh);
    };
  }, []);

  return profile;
}
