import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { useTheme } from './useTheme';

describe('useTheme', () => {
  beforeEach(() => {
    document.documentElement.classList.remove('dark');
    localStorage.clear();
  });

  afterEach(() => {
    document.documentElement.classList.remove('dark');
    localStorage.clear();
  });

  it('toggleTheme flips the dark class on <html> and persists to localStorage', () => {
    const { result } = renderHook(() => useTheme());
    const initial = result.current.theme;
    const expected = initial === 'dark' ? 'light' : 'dark';

    act(() => {
      result.current.toggleTheme();
    });

    expect(result.current.theme).toBe(expected);
    expect(document.documentElement.classList.contains('dark')).toBe(expected === 'dark');
    expect(localStorage.getItem('theme')).toBe(expected);
  });

  it('keeps multiple mounted instances in sync when one of them toggles', () => {
    const a = renderHook(() => useTheme());
    const b = renderHook(() => useTheme());

    act(() => {
      a.result.current.toggleTheme();
    });

    expect(a.result.current.theme).toBe(b.result.current.theme);
  });
});
