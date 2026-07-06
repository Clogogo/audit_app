import { useAuth } from '../contexts/AuthContext';
import { LoadingScreen } from './LoadingScreen';
import { Landing } from '../pages/Landing';
import { Layout } from './Layout';
import { Dashboard } from '../pages/Dashboard';

// "/" is the one route that isn't strictly public or protected, it shows
// the marketing Landing page to a signed-out visitor, or the Dashboard
// (inside the normal app Layout) to a signed-in one, so bookmarking "/"
// keeps working exactly as before for existing logged-in users.
export function HomeRoute() {
  const { isAuthenticated, loading } = useAuth();

  if (loading) {
    return <LoadingScreen />;
  }

  if (isAuthenticated) {
    return (
      <Layout>
        <Dashboard />
      </Layout>
    );
  }

  return <Landing />;
}
