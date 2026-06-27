import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { KeyRound, Wallet } from 'lucide-react';
import axios from 'axios';
import { resetPassword } from '../api/client';
import { useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';

export function ResetPassword() {
  const navigate = useNavigate();
  const notify = useNotification();
  const [searchParams] = useSearchParams();
  const token = searchParams.get('token') ?? '';

  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (newPassword.length < 6) {
      notify.error('Password must be at least 6 characters');
      return;
    }
    if (newPassword !== confirmPassword) {
      notify.error('Passwords do not match');
      return;
    }

    setLoading(true);
    try {
      await resetPassword(token, newPassword);
      notify.success('✅ Password updated. You can now log in.');
      navigate('/login');
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.data?.detail) {
        notify.error(`❌ ${err.response.data.detail}`);
      } else {
        notify.error('❌ Could not reset password. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-900 dark:to-slate-950 p-4">
      <Card className="w-full max-w-md">
        <CardHeader className="space-y-3">
          <div className="flex items-center justify-center gap-2 text-primary mb-2">
            <Wallet className="h-10 w-10" />
            <h1 className="text-3xl font-bold">FinanceAudit</h1>
          </div>
          <CardTitle className="text-center">Set a New Password</CardTitle>
          <CardDescription className="text-center">
            Choose a new password for your account
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!token ? (
            <p className="text-center text-sm text-destructive py-2">
              This link is missing its reset token. Use the link from your email, or request a new one.
            </p>
          ) : (
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="newPassword">
                  New Password <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="newPassword"
                  type="password"
                  placeholder="••••••••"
                  value={newPassword}
                  onChange={(e) => setNewPassword(e.target.value)}
                  required
                  minLength={6}
                  disabled={loading}
                />
                <p className="text-xs text-muted-foreground">Minimum 6 characters</p>
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">
                  Confirm New Password <span className="text-destructive">*</span>
                </Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  placeholder="••••••••"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  minLength={6}
                  disabled={loading}
                />
              </div>
              <Button type="submit" className="w-full" disabled={loading}>
                {loading ? (
                  <>Updating password...</>
                ) : (
                  <>
                    <KeyRound className="h-4 w-4 mr-2" />
                    Update Password
                  </>
                )}
              </Button>
            </form>
          )}

          <p className="text-center text-sm text-muted-foreground mt-4">
            <Link to="/login" className="text-primary hover:underline font-medium">
              Back to sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
