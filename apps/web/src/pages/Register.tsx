import { useState } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { UserPlus } from 'lucide-react';
import { useAuth } from '../contexts/AuthContext';
import { useNotification } from '../hooks';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import { AuthLayout } from '../components/AuthLayout';

export function Register() {
  const navigate = useNavigate();
  const { register } = useAuth();
  const notify = useNotification();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [fullName, setFullName] = useState('');
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();

    if (password.length < 6) {
      notify.error('Password must be at least 6 characters');
      return;
    }

    setLoading(true);

    try {
      await register(email, password, fullName);
      notify.success('🎉 Account created successfully! Welcome aboard!');
      navigate('/');
    } catch (err: any) {
      // Handle validation errors from FastAPI/Pydantic
      if (err.response?.data?.detail) {
        const detail = err.response.data.detail;

        // Check if it's a validation error array
        if (Array.isArray(detail)) {
          const emailError = detail.find((e: any) => e.loc?.includes('email'));
          if (emailError) {
            notify.error('📧 Invalid email format. Please use a valid email like: user@example.com');
          } else {
            notify.error(`❌ ${detail[0].msg || 'Validation error'}`);
          }
        } else if (typeof detail === 'string') {
          // Handle string errors like "Email already registered"
          if (detail.toLowerCase().includes('already')) {
            notify.error('⚠️ This email is already registered. Try logging in instead.');
          } else {
            notify.error(`❌ ${detail}`);
          }
        }
      } else {
        notify.error('❌ Registration failed. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthLayout
      title="Create an Account"
      description="Sign up to start managing your finances"
      footer={
        <>
          Already have an account?{' '}
          <Link to="/login" className="text-primary hover:underline font-medium">
            Sign in here
          </Link>
        </>
      }
    >
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor="fullName">Full Name</Label>
          <Input
            id="fullName"
            type="text"
            placeholder="Ngozi Adeyemi"
            value={fullName}
            onChange={(e) => setFullName(e.target.value)}
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
            placeholder="user@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            disabled={loading}
          />
          <p className="text-xs text-muted-foreground">
            Use a valid email format (e.g., user@domain.com)
          </p>
        </div>
        <div className="space-y-2">
          <Label htmlFor="password">
            Password <span className="text-destructive">*</span>
          </Label>
          <Input
            id="password"
            type="password"
            placeholder="••••••••"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            minLength={6}
            disabled={loading}
          />
          <p className="text-xs text-muted-foreground">
            Minimum 6 characters
          </p>
        </div>
        <Button type="submit" className="w-full" disabled={loading}>
          {loading ? (
            <>Creating account...</>
          ) : (
            <>
              <UserPlus className="h-4 w-4 mr-2" />
              Create Account
            </>
          )}
        </Button>
      </form>
    </AuthLayout>
  );
}
