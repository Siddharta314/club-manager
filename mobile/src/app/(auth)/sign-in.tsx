import { useSignIn, useAuth, useSSO } from '@clerk/expo';
import { Link, useRouter } from 'expo-router';
import { useState } from 'react';
import {
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from 'react-native';

export default function SignInScreen() {
  const { signIn } = useSignIn();
  const { isLoaded } = useAuth();
  const { startSSOFlow } = useSSO();
  const router = useRouter();

  const [emailAddress, setEmailAddress] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isLoaded) return null;

  const onOAuthPress = async (strategy: 'oauth_google' | 'oauth_apple') => {
    setSubmitting(true);
    setError(null);
    try {
      const { createdSessionId, setActive: setActiveFromSSO } =
        await startSSOFlow({ strategy });
      if (createdSessionId && setActiveFromSSO) {
        await setActiveFromSSO({ session: createdSessionId });
        router.replace('/(app)/home');
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'OAuth sign-in failed');
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const { error: pwError } = await signIn.password({
        identifier: emailAddress,
        password,
      });
      if (pwError) {
        setError(pwError.message ?? 'Sign-in failed');
        return;
      }
      if (signIn.status !== 'complete') {
        // Other statuses (e.g., needs_first_factor) — surface to user.
        setError(`Sign-in needs additional step: ${signIn.status ?? 'unknown'}`);
        return;
      }
      const { error: finalizeError } = await signIn.finalize();
      if (finalizeError) {
        setError(finalizeError.message ?? 'Could not activate session');
        return;
      }
      router.replace('/(app)/home');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sign-in failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.container}
    >
      <Text style={styles.title}>Sign in</Text>
      <TextInput
        style={styles.input}
        placeholder="Email"
        autoCapitalize="none"
        keyboardType="email-address"
        value={emailAddress}
        onChangeText={setEmailAddress}
      />
      <TextInput
        style={styles.input}
        placeholder="Password"
        secureTextEntry
        value={password}
        onChangeText={setPassword}
      />
      {error && <Text style={styles.error}>{error}</Text>}
      <Pressable
        style={[styles.button, submitting && styles.buttonDisabled]}
        onPress={onSubmit}
        disabled={submitting}
      >
        {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Sign in</Text>}
      </Pressable>
      <View style={styles.divider}><Text style={styles.dividerText}>or</Text></View>
      <Pressable
        style={[styles.oauthButton, submitting && styles.buttonDisabled]}
        onPress={() => onOAuthPress('oauth_google')}
        disabled={submitting}
      >
        <Text style={styles.oauthButtonText}>Continue with Google</Text>
      </Pressable>
      <Pressable
        style={[styles.oauthButton, submitting && styles.buttonDisabled]}
        onPress={() => onOAuthPress('oauth_apple')}
        disabled={submitting}
      >
        <Text style={styles.oauthButtonText}>Continue with Apple</Text>
      </Pressable>
      <View style={styles.links}>
        <Link href="/(auth)/forgot-password" style={styles.link}>Forgot password?</Link>
        <Link href="/(auth)/sign-up" style={styles.link}>Don't have an account? Sign up</Link>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, justifyContent: 'center' },
  title: { fontSize: 28, fontWeight: '700', marginBottom: 24 },
  input: {
    borderWidth: 1, borderColor: '#ccc', borderRadius: 8,
    padding: 12, marginBottom: 12, fontSize: 16,
  },
  error: { color: '#c00', marginBottom: 12 },
  button: {
    backgroundColor: '#0a7', padding: 14, borderRadius: 8,
    alignItems: 'center', marginTop: 4,
  },
  buttonDisabled: { opacity: 0.5 },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
  divider: { flexDirection: 'row', alignItems: 'center', marginVertical: 16 },
  dividerText: { color: '#666', marginHorizontal: 8 },
  oauthButton: {
    borderWidth: 1, borderColor: '#ccc', padding: 14, borderRadius: 8,
    alignItems: 'center', marginBottom: 8, backgroundColor: '#fff',
  },
  oauthButtonText: { color: '#000', fontSize: 16, fontWeight: '500' },
  links: { marginTop: 16, alignItems: 'center' },
  link: { color: '#06c', marginVertical: 4 },
});
