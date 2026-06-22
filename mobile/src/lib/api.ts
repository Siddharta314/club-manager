import { useAuth } from '@clerk/expo';

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