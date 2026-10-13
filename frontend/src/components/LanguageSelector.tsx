import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { listLanguagesApi } from '../lib/paperTools';

type LanguageSelectorProps = {
  value: string | null; // null = English (no translation requested)
  onChange: (lang: string | null) => void;
};

// Phase 18: a language selector on the paper detail page that switches
// summary/explanations/review/chat into the chosen language. The whitelist
// itself comes from the backend (same pattern as the discover page's
// category chips) so a language only ever appears here once it's actually
// been verified end-to-end, not just because the underlying model supports it.
export default function LanguageSelector({ value, onChange }: LanguageSelectorProps) {
  const { token } = useAuth();
  const [languages, setLanguages] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!token) return;
    listLanguagesApi(token)
      .then(setLanguages)
      .catch(() => {
        // Leave the list empty — the selector just shows "English" only.
      });
  }, [token]);

  if (Object.keys(languages).length === 0) return null;

  return (
    <select
      value={value ?? 'en'}
      onChange={(event) => onChange(event.target.value === 'en' ? null : event.target.value)}
      className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-600 outline-none transition focus:border-brand-500"
      aria-label="Display language"
    >
      <option value="en">English</option>
      {Object.entries(languages).map(([code, name]) => (
        <option key={code} value={code}>
          {name}
        </option>
      ))}
    </select>
  );
}
