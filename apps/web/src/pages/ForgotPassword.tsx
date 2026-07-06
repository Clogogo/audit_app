import { useState } from 'react';
import { Link } from 'react-router-dom';
import { Mail, CheckCircle2 } from 'lucide-react';
import { requestPasswordReset } from '../api/client';
import { useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { AuthLayout } from '../components/AuthLayout';

export function ForgotPassword() {
  const notify = useNotification();

  const [email, setEmail] = useState('');
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    try {
      await requestPasswordReset(email);
      setSent(true);
    } catch {
      notify.error('❌ Could not send reset email. Please try again.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Reset Password"
      description="Enter your account email and we'll send you a reset link"
      footer={
        <>
          Remembered it after all?{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            Back to sign in
          </Link>
        </>
      }
    >
      {sent ? (
        <div className="text-center space-y-3 py-2">
          <CheckCircle2 className="h-10 w-10 text-income mx-auto" />
          <p className="text-sm text-foreground">
            If <strong>{email}</strong> is registered, a password reset link has been sent.
            It expires in 30 minutes.
          </p>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-4">
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
          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? (
              <>Sending...</>
            ) : (
              <>
                <Mail className="h-4 w-4 mr-2" />
                Send Reset Link
              </>
            )}
          </Button>
        </form>
      )}
    </AuthLayout>
  );
}
