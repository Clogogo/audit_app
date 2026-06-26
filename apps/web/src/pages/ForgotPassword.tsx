import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { KeyRound, Wallet } from 'lucide-react';
import axios from 'axios';
import { forgotPassword } from '../api/client';
import { useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '../components/ui/card';

export function ForgotPassword() {
  const navigate = useNavigate();
  const notify = useNotification();

  const [email, setEmail] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [recoveryCode, setRecoveryCode] = useState('');
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
      await forgotPassword(email, newPassword, recoveryCode);
      notify.success('✅ Password updated. You can now log in.');
      navigate('/login');
    } catch (err: unknown) {
      if (axios.isAxiosError(err) && err.response?.status === 404) {
        notify.error('📧 No account found with that email.');
      } else if (axios.isAxiosError(err) && err.response?.data?.detail) {
        notify.error(`❌ ${err.response.data.detail}`);
      } else {
        notify.error('❌ Could not reset password. Please try again.');
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
          <CardTitle className="text-center">Reset Password</CardTitle>
          <CardDescription className="text-center">
            Enter your account email, recovery code, and a new password
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="recoveryCode">
                Recovery Code <span className="text-destructive">*</span>
              </Label>
              <Input
                id="recoveryCode"
                type="text"
                placeholder="Set by your admin in the server environment"
                value={recoveryCode}
                onChange={(e) => setRecoveryCode(e.target.value)}
                required
                disabled={loading}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="email">
                Email <span className="text-destructive">*</span>
              </Label>
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

          <p className="text-center text-sm text-muted-foreground mt-4">
            Remembered it after all?{' '}
            <Link to="/login" className="text-primary hover:underline font-medium">
              Back to sign in
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
