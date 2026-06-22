import { useSignUp, useAuth, useSSO } from '@clerk/expo';
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

export default function SignUpScreen() {
  const { signUp } = useSignUp();
  const { isLoaded } = useAuth();
  const { startSSOFlow } = useSSO();
  const router = useRouter();

  const [emailAddress, setEmailAddress] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [pendingVerification, setPendingVerification] = useState(false);
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
      setError(e instanceof Error ? e.message : 'OAuth sign-up failed');
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmitEmail = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const { error: createError } = await signUp.password({
        emailAddress,
        password,
      });
      if (createError) {
        setError(createError.message ?? 'Sign-up failed');
        return;
      }
      const { error: sendError } = await signUp.verifications.sendEmailCode();
      if (sendError) {
        setError(sendError.message ?? 'Could not send verification code');
        return;
      }
      setPendingVerification(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Sign-up failed');
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmitCode = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const { error: verifyError } = await signUp.verifications.verifyEmailCode({ code });
      if (verifyError) {
        setError(verifyError.message ?? 'Verification failed');
        return;
      }
      if (signUp.status !== 'complete') {
        setError(`Sign-up needs additional step: ${signUp.status}`);
        return;
      }
      const { error: finalizeError } = await signUp.finalize();
      if (finalizeError) {
        setError(finalizeError.message ?? 'Could not activate session');
        return;
      }
      router.replace('/(app)/home');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Verification failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.container}
    >
      {!pendingVerification ? (
        <>
          <Text style={styles.title}>Create account</Text>
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
            onPress={onSubmitEmail}
            disabled={submitting}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Continue</Text>}
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
            <Link href="/(auth)/sign-in" style={styles.link}>Already have an account? Sign in</Link>
          </View>
        </>
      ) : (
        <>
          <Text style={styles.title}>Verify email</Text>
          <Text style={styles.subtitle}>We sent a 6-digit code to {emailAddress}.</Text>
          <TextInput
            style={styles.input}
            placeholder="123456"
            keyboardType="number-pad"
            value={code}
            onChangeText={setCode}
            maxLength={6}
          />
          {error && <Text style={styles.error}>{error}</Text>}
          <Pressable
            style={[styles.button, submitting && styles.buttonDisabled]}
            onPress={onSubmitCode}
            disabled={submitting}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Verify</Text>}
          </Pressable>
        </>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, justifyContent: 'center' },
  title: { fontSize: 28, fontWeight: '700', marginBottom: 16 },
  subtitle: { fontSize: 14, color: '#666', marginBottom: 16 },
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
