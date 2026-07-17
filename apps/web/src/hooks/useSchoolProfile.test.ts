import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { getSchoolProfileMock } = vi.hoisted(() => ({
  getSchoolProfileMock: vi.fn(),
}));

vi.mock('../api/client', () => ({
  getSchoolProfile: getSchoolProfileMock,
}));

import { broadcastSchoolProfileUpdated, useSchoolProfile } from './useSchoolProfile';

const PROFILE_A = {
  name: 'Marvelous Light School',
  tagline: 'LEARN SHINE LEAD',
  country: 'Nigeria',
  logo: null,
};

describe('useSchoolProfile', () => {
  it('fetches the profile on first mount', async () => {
    getSchoolProfileMock.mockResolvedValue(PROFILE_A);
    const { result } = renderHook(() => useSchoolProfile());
    await waitFor(() => expect(result.current?.name).toBe('Marvelous Light School'));
  });

  it('a freshly mounted instance renders the cached profile synchronously (no flash)', () => {
    // The Dashboard route mounts its own Layout — this simulates that remount.
    // The cache from the previous test's fetch must be visible before any
    // network response resolves.
    getSchoolProfileMock.mockReturnValue(new Promise(() => {})); // never resolves
    const { result } = renderHook(() => useSchoolProfile());
    expect(result.current?.name).toBe('Marvelous Light School');
  });

  it('broadcastSchoolProfileUpdated re-fetches and updates mounted consumers', async () => {
    getSchoolProfileMock.mockResolvedValue({ ...PROFILE_A, name: 'Renamed School' });
    const { result } = renderHook(() => useSchoolProfile());
    act(() => {
      broadcastSchoolProfileUpdated();
    });
    await waitFor(() => expect(result.current?.name).toBe('Renamed School'));
  });
});
