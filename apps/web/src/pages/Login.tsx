import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { LogIn, Wallet } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';

export function Login() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const notify = useNotification();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);

    try {
      await login(email, password);
      notify.success('✅ Welcome back! Login successful.');
      navigate('/');
    } catch (err: any) {
      // Handle different error types
      if (err.response?.status === 401) {
        notify.error('🔒 Incorrect email or password. Please try again.');
      } else if (err.response?.status === 403) {
        notify.error('⚠️ Your account has been deactivated. Please contact support.');
      } else if (err.response?.data?.detail) {
        const detail = err.response.data.detail;

        // Handle validation errors
        if (Array.isArray(detail)) {
          const emailError = detail.find((e: any) => e.loc?.includes('email'));
          if (emailError) {
            notify.error('📧 Please enter a valid email address.');
          } else {
            notify.error(`❌ ${detail[0].msg || 'Invalid input'}`);
          }
        } else {
          notify.error(`❌ ${detail}`);
        }
      } else {
        notify.error('❌ Login failed. Please check your connection and try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3">
          <div className="flex items-center justify-center gap-2 text-primary mb-2">
            <Wallet className="h-10 w-10" />
            <h1 className="text-3xl font-bold">FinanceAudit</h1>
          </div>
          <CardTitle className="text-center">Welcome Back</CardTitle>
          <CardDescription className="text-center">
            Sign in to your account to continue
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label htmlFor="password">Password</Label>
                <Link to="/forgot-password" className="text-xs text-primary hover:underline">
                  Forgot password?
                </Link>
              </div>
              <Input
                id="password"
                type="password"
                placeholder="••••••••"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <Button type="submit" className="w-full" disabled={loading}>
              {loading ? (
                <>Signing in...</>
              ) : (
                <>
                  <LogIn className="h-4 w-4 mr-2" />
                  Sign In
                </>
              )}
            </Button>
          </form>

          <p className="text-center text-sm text-muted-foreground mt-4">
            Don't have an account?{' '}
            <Link to="/register" className="text-primary hover:underline font-medium">
              Register here
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
