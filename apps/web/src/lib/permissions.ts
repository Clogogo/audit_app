import type { User } from '../api/types';

/** The one place a permission check lives — everything else (nav filtering,
 * route guards) calls this instead of re-deriving it from user.role. */
export function hasPermission(user: User | null | undefined, key: string): boolean {
  return user?.role?.permissions.includes(key) ?? false;
}
