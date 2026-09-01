export type FormErrors = Record<string, string>;

const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(value: string): string | null {
  if (!value.trim()) return 'Email is required';
  if (!emailPattern.test(value)) return 'Enter a valid email address';
  return null;
}

export function validatePassword(value: string): string | null {
  if (!value) return 'Password is required';
  if (value.length < 8) return 'Password must be at least 8 characters';
  return null;
}

export function validateSignupForm(data: {
  email: string;
  password: string;
  confirmPassword: string;
  full_name: string;
}): FormErrors {
  const errors: FormErrors = {};
  const emailError = validateEmail(data.email);
  const passwordError = validatePassword(data.password);

  if (emailError) errors.email = emailError;
  if (passwordError) errors.password = passwordError;
  if (data.password !== data.confirmPassword) errors.confirmPassword = 'Passwords do not match';

  return errors;
}

export function validateLoginForm(data: { email: string; password: string }): FormErrors {
  const errors: FormErrors = {};
  const emailError = validateEmail(data.email);
  const passwordError = validatePassword(data.password);

  if (emailError) errors.email = emailError;
  if (passwordError) errors.password = passwordError;

  return errors;
}