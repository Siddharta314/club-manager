import { useSignIn, useAuth } from '@clerk/expo';
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

export default function ForgotPasswordScreen() {
  const { signIn } = useSignIn();
  const { isLoaded } = useAuth();
  const router = useRouter();

  const [emailAddress, setEmailAddress] = useState('');
  const [code, setCode] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [pendingReset, setPendingReset] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isLoaded) return null;

  const onRequestReset = async () => {
    setSubmitting(true);
    setError(null);
    try {
      // Initialize the sign-in with the identifier so the reset code is
      // routed to that account.
      const { error: createError } = await signIn.create({
        identifier: emailAddress,
      });
      if (createError) {
        setError(createError.message ?? 'Reset request failed');
        return;
      }
      const { error: sendError } = await signIn.resetPasswordEmailCode.sendCode();
      if (sendError) {
        setError(sendError.message ?? 'Could not send reset code');
        return;
      }
      setPendingReset(true);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Reset request failed');
    } finally {
      setSubmitting(false);
    }
  };

  const onSubmitReset = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const { error: verifyError } = await signIn.resetPasswordEmailCode.verifyCode({
        code,
      });
      if (verifyError) {
        setError(verifyError.message ?? 'Invalid code');
        return;
      }
      const { error: submitError } = await signIn.resetPasswordEmailCode.submitPassword({
        password: newPassword,
      });
      if (submitError) {
        setError(submitError.message ?? 'Could not set new password');
        return;
      }
      if (signIn.status !== 'complete') {
        setError(`Reset needs additional step: ${signIn.status}`);
        return;
      }
      // Session is now established — send the user back to sign-in so they
      // can log in with the new password explicitly (SCENARIO-MOBILE-B06).
      router.replace('/(auth)/sign-in');
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : 'Reset failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      style={styles.container}
    >
      {!pendingReset ? (
        <>
          <Text style={styles.title}>Reset password</Text>
          <TextInput
            style={styles.input}
            placeholder="Email"
            autoCapitalize="none"
            keyboardType="email-address"
            value={emailAddress}
            onChangeText={setEmailAddress}
          />
          {error && <Text style={styles.error}>{error}</Text>}
          <Pressable
            style={[styles.button, submitting && styles.buttonDisabled]}
            onPress={onRequestReset}
            disabled={submitting}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Send reset code</Text>}
          </Pressable>
          <View style={styles.links}>
            <Link href="/(auth)/sign-in" style={styles.link}>Back to sign in</Link>
          </View>
        </>
      ) : (
        <>
          <Text style={styles.title}>Enter code + new password</Text>
          <Text style={styles.subtitle}>We sent a 6-digit code to {emailAddress}.</Text>
          <TextInput
            style={styles.input}
            placeholder="123456"
            keyboardType="number-pad"
            value={code}
            onChangeText={setCode}
            maxLength={6}
          />
          <TextInput
            style={styles.input}
            placeholder="New password"
            secureTextEntry
            value={newPassword}
            onChangeText={setNewPassword}
          />
          {error && <Text style={styles.error}>{error}</Text>}
          <Pressable
            style={[styles.button, submitting && styles.buttonDisabled]}
            onPress={onSubmitReset}
            disabled={submitting}
          >
            {submitting ? <ActivityIndicator color="#fff" /> : <Text style={styles.buttonText}>Reset password</Text>}
          </Pressable>
        </>
      )}
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, justifyContent: 'center' },
  title: { fontSize: 24, fontWeight: '700', marginBottom: 16 },
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
  links: { marginTop: 16, alignItems: 'center' },
  link: { color: '#06c', marginVertical: 4 },
});
