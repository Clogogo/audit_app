import { useEffect, useRef, useState } from 'react';
import { Camera, Pencil, RefreshCw, School } from 'lucide-react';
import { getSchoolProfile, updateSchoolProfile, uploadSchoolLogo } from '../api/client';
import type { SchoolProfileIn } from '../api/types';
import { Button } from '../components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '../components/ui/card';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select';
import { useNotification } from '../hooks';

const MAX_LOGO_BYTES = 500 * 1024;

const COUNTRIES = [
  'Nigeria', 'Ghana', 'Benin', 'Togo', 'Cameroon', 'Niger', 'Chad',
  'Senegal', 'Ivory Coast', 'Sierra Leone', 'Liberia', 'Gambia',
  'Kenya', 'Uganda', 'Tanzania', 'Rwanda', 'Ethiopia',
  'South Africa', 'Zambia', 'Zimbabwe', 'Botswana', 'Egypt', 'Morocco',
  'United Kingdom', 'United States', 'Canada', 'Other',
];

const EMPTY_FORM: SchoolProfileIn = {
  name: '',
  tagline: '',
  phone: '',
  website: '',
  address: '',
  country: 'Nigeria',
};

function FieldLabel({ children, required }: { children: React.ReactNode; required?: boolean }) {
  return (
    <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
      {children}
      {required && <span className="ml-0.5 text-red-500">*</span>}
    </Label>
  );
}

export function SchoolProfile() {
  const { success, error: notifyError } = useNotification();
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [form, setForm] = useState<SchoolProfileIn>(EMPTY_FORM);
  const [logo, setLogo] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [uploadingLogo, setUploadingLogo] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getSchoolProfile()
      .then((p) => {
        setForm({
          name: p.name ?? '',
          tagline: p.tagline ?? '',
          phone: p.phone ?? '',
          website: p.website ?? '',
          address: p.address ?? '',
          country: p.country || 'Nigeria',
        });
        setLogo(p.logo ?? null);
      })
      .catch(() => setError('Failed to load school profile'))
      .finally(() => setLoading(false));
  }, []);

  const set = (field: keyof SchoolProfileIn) =>
    (e: React.ChangeEvent<HTMLInputElement>) =>
      setForm((f) => ({ ...f, [field]: e.target.value }));

  const handleLogoSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // allow re-selecting the same file
    if (!file) return;
    if (!['image/jpeg', 'image/png'].includes(file.type)) {
      notifyError('Only JPG or PNG images are supported.');
      return;
    }
    if (file.size > MAX_LOGO_BYTES) {
      notifyError('Logo is too large. Maximum size is 500KB.');
      return;
    }
    setUploadingLogo(true);
    try {
      const updated = await uploadSchoolLogo(file);
      setLogo(updated.logo ?? null);
      window.dispatchEvent(new Event('school-profile-updated'));
      success('Logo updated');
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      notifyError(detail || 'Failed to upload logo');
    } finally {
      setUploadingLogo(false);
    }
  };

  const handleSave = async () => {
    if (!form.name.trim()) {
      setError('Name of institute is required.');
      return;
    }
    if (!form.phone?.trim() || !form.address?.trim()) {
      setError('Phone number and address are required.');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      await updateSchoolProfile({
        ...form,
        name: form.name.trim(),
        tagline: form.tagline?.trim() || null,
        phone: form.phone?.trim() || null,
        website: form.website?.trim() || null,
        address: form.address?.trim() || null,
      });
      window.dispatchEvent(new Event('school-profile-updated'));
      success('School profile updated');
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Failed to update school profile');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return <div className="p-6 text-muted-foreground">Loading school profile…</div>;
  }

  return (
    <div className="p-4 md:p-6 max-w-5xl mx-auto">
      <Card>
        <CardHeader className="border-b">
          <CardTitle className="flex items-center gap-2 text-xl">
            <Pencil className="h-5 w-5 text-primary" />
            Update Profile
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-6 space-y-6">
          <p className="text-sm text-muted-foreground">
            <span className="text-red-500">*</span> Indicates required fields
          </p>

          {error && (
            <div className="rounded-md border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
              {error}
            </div>
          )}

          <div className="grid gap-8 md:grid-cols-2">
            {/* Left column */}
            <div className="space-y-6">
              <div className="space-y-2">
                <FieldLabel>Institute Logo</FieldLabel>
                <div className="flex items-center gap-4">
                  <div className="flex h-28 w-28 items-center justify-center overflow-hidden rounded-xl border bg-card">
                    {logo ? (
                      <img src={logo} alt="School logo" className="h-full w-full object-contain" />
                    ) : (
                      <School className="h-10 w-10 text-muted-foreground/40" />
                    )}
                  </div>
                  <div className="space-y-1">
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => fileInputRef.current?.click()}
                      disabled={uploadingLogo}
                    >
                      <Camera className="mr-2 h-4 w-4" />
                      {uploadingLogo ? 'Uploading…' : 'Change Logo'}
                    </Button>
                    <p className="text-xs text-muted-foreground">JPG, PNG. Max 500KB</p>
                  </div>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept="image/jpeg,image/png"
                    className="hidden"
                    onChange={handleLogoSelect}
                  />
                </div>
              </div>

              <div className="space-y-2">
                <FieldLabel required>Name of Institute</FieldLabel>
                <Input value={form.name} onChange={set('name')} placeholder="School name" />
              </div>

              <div className="space-y-2">
                <FieldLabel required>Target Line</FieldLabel>
                <Input
                  value={form.tagline ?? ''}
                  onChange={set('tagline')}
                  placeholder="e.g. LEARN SHINE LEAD"
                />
              </div>
            </div>

            {/* Right column */}
            <div className="space-y-6">
              <div className="space-y-2">
                <FieldLabel required>Phone Number</FieldLabel>
                <Input
                  value={form.phone ?? ''}
                  onChange={set('phone')}
                  placeholder="+234..., +234..."
                />
              </div>

              <div className="space-y-2">
                <FieldLabel>Website</FieldLabel>
                <Input
                  value={form.website ?? ''}
                  onChange={set('website')}
                  placeholder="Website URL"
                />
              </div>

              <div className="space-y-2">
                <FieldLabel required>Address</FieldLabel>
                <Input
                  value={form.address ?? ''}
                  onChange={set('address')}
                  placeholder="School address"
                />
              </div>

              <div className="space-y-2">
                <FieldLabel required>Country</FieldLabel>
                <Select
                  value={form.country}
                  onValueChange={(v) => setForm((f) => ({ ...f, country: v }))}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select country" />
                  </SelectTrigger>
                  <SelectContent>
                    {COUNTRIES.map((c) => (
                      <SelectItem key={c} value={c}>
                        {c}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>

          <div className="flex justify-center pt-2">
            <Button onClick={handleSave} disabled={saving} className="px-8">
              <RefreshCw className={saving ? 'mr-2 h-4 w-4 animate-spin' : 'mr-2 h-4 w-4'} />
              {saving ? 'Updating…' : 'Update Profile'}
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
