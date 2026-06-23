import { useAuth } from '@clerk/expo';
import { randomUUID } from 'expo-crypto';

export type ApiError = { status: number; message: string };

export async function apiGet<T>(path: string): Promise<T> {
  const { getToken } = useAuth();
  const token = await getToken();
  if (!token) throw { status: 401, message: 'No session token' } satisfies ApiError;

  const res = await fetch(`${process.env.EXPO_PUBLIC_API_URL}${path}`, {
    headers: { Authorization: `Bearer ${token}` },
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw { status: res.status, message: text || res.statusText } satisfies ApiError;
  }
  return res.json() as Promise<T>;
}

export async function apiPost<T, B>(
  path: string,
  body: B,
  idemKey?: string,
): Promise<T> {
  const { getToken } = useAuth();
  const token = await getToken();
  if (!token) throw { status: 401, message: 'No session token' } satisfies ApiError;

  const key = idemKey ?? randomUUID();
  const res = await fetch(`${process.env.EXPO_PUBLIC_API_URL}${path}`, {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${token}`,
      'Content-Type': 'application/json',
      'Idempotency-Key': key,
    },
    body: JSON.stringify(body),
  });

  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw { status: res.status, message: text || res.statusText } satisfies ApiError;
  }
  return res.json() as Promise<T>;
}