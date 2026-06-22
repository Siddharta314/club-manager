import { Redirect } from 'expo-router';
import { useAuth } from '@clerk/expo';

export default function Index() {
  const { isSignedIn, isLoaded } = useAuth();
  if (!isLoaded) return null;
  return <Redirect href={isSignedIn ? '/(app)/home' : '/(auth)/sign-in'} />;
}