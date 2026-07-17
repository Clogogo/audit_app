import { useEffect, useState } from 'react';
import { getSchoolProfile } from '../api/client';
import type { SchoolProfile } from '../api/types';

const STORAGE_KEY = 'school-profile-cache';
const UPDATED_EVENT = 'school-profile-updated';

// Module-level cache: the Dashboard route ("/") mounts its own Layout
// instance, so navigating to/from it remounts the header. Without a cache
// each fresh mount starts at null and flashes stale/fallback branding until
// its fetch resolves; with it, the last known profile renders instantly and
// the fetch only refreshes it in the background. localStorage seeds the
// cache across full page reloads.
let cached: SchoolProfile | null = null;

function readStoredProfile(): SchoolProfile | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    return raw ? (JSON.parse(raw) as SchoolProfile) : null;
  } catch {
    return null;
  }
}

/** Notify every mounted useSchoolProfile consumer to re-fetch (call after
 * saving the profile or uploading a logo). */
export function broadcastSchoolProfileUpdated() {
  window.dispatchEvent(new Event(UPDATED_EVENT));
}

export function useSchoolProfile(): SchoolProfile | null {
  const [profile, setProfile] = useState<SchoolProfile | null>(
    () => cached ?? (cached = readStoredProfile())
  );

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      getSchoolProfile()
        .then((p) => {
          cached = p;
          try {
            localStorage.setItem(STORAGE_KEY, JSON.stringify(p));
          } catch {
            // storage full or unavailable — memory cache still works
          }
          if (!cancelled) setProfile(p);
        })
        .catch(() => {
          // branding is optional — keep the last known value
        });
    load();
    window.addEventListener(UPDATED_EVENT, load);
    return () => {
      cancelled = true;
      window.removeEventListener(UPDATED_EVENT, load);
    };
  }, []);

  return profile;
}
