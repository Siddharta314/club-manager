import { useUser, useAuth } from '@clerk/expo';
import { useQuery } from '@tanstack/react-query';
import { ActivityIndicator, StyleSheet, Text, View } from 'react-native';

import { apiGet, ApiError } from '@/lib/api';

type Me = {
  id: number;
  email: string;
  name: string;
  level: number;
};

export default function Home() {
  const { user } = useUser();
  const me = useQuery<Me, ApiError>({
    queryKey: ['me'],
    queryFn: () => apiGet<Me>('/me/'),
  });

  return (
    <View style={styles.container}>
      <Text style={styles.greeting}>Hello {user?.firstName ?? 'player'}</Text>
      {me.isLoading && <ActivityIndicator />}
      {me.data && <Text style={styles.level}>Level: {me.data.level}</Text>}
      {me.error && <Text style={styles.error}>Error: {me.error.message}</Text>}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20, justifyContent: 'center' },
  greeting: { fontSize: 24, fontWeight: '600', marginBottom: 16 },
  level: { fontSize: 18, marginTop: 8 },
  error: { fontSize: 14, color: '#c00', marginTop: 8 },
});