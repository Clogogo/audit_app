import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { HomeRoute } from './HomeRoute';
import { useAuth } from '../contexts/AuthContext';

vi.mock('../contexts/AuthContext', () => ({
  useAuth: vi.fn(),
}));

// Dashboard renders live API-backed charts/data, and Layout independently
// reads user/logout off useAuth() — both out of scope here, which only
// cares which branch HomeRoute picks.
vi.mock('../pages/Dashboard', () => ({
  Dashboard: () => <div>dashboard-content</div>,
}));
vi.mock('./Layout', () => ({
  Layout: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

describe('HomeRoute', () => {
  it('shows a loading screen while auth state is resolving', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: false, loading: true } as ReturnType<typeof useAuth>);
    render(<MemoryRouter><HomeRoute /></MemoryRouter>);
    expect(screen.getByText('Loading...')).toBeInTheDocument();
  });

  it('shows the Landing page when signed out', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: false, loading: false } as ReturnType<typeof useAuth>);
    render(<MemoryRouter><HomeRoute /></MemoryRouter>);
    // "Sign In" intentionally repeats (nav, hero, closing CTA) - same
    // label/intent every time, not a duplicate-intent violation.
    expect(screen.getAllByRole('link', { name: 'Sign In' }).length).toBeGreaterThan(0);
    expect(screen.queryByText('dashboard-content')).not.toBeInTheDocument();
  });

  it('shows the Dashboard inside the app Layout when signed in', () => {
    vi.mocked(useAuth).mockReturnValue({ isAuthenticated: true, loading: false } as ReturnType<typeof useAuth>);
    render(<MemoryRouter><HomeRoute /></MemoryRouter>);
    expect(screen.getByText('dashboard-content')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Sign In' })).not.toBeInTheDocument();
  });
});
