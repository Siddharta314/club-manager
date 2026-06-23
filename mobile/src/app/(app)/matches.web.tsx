import { useQuery } from '@tanstack/react-query';
import { ActivityIndicator, ScrollView, StyleSheet, Text, View } from 'react-native';
import { useRouter } from 'expo-router';

import { apiGet, ApiError } from '@/lib/api';
import MatchCard from '@/components/MatchCard.web';

type CourtBrief = { id: number; name: string };

type MatchPlayerBrief = {
  user_id: number;
  user_name: string;
  user_level: number;
  is_host: boolean;
};

type MatchCapacity = {
  player_count: number;
  companion_count: number;
  total: number;
  is_full: boolean;
  is_open: boolean;
  is_in_progress: boolean;
  is_finished: boolean;
};

type Match = {
  id: number;
  court: CourtBrief;
  start_time: string;
  end_time: string;
  level_min: number;
  level_max: number;
  is_cancelled: boolean;
  players: MatchPlayerBrief[];
  capacity: MatchCapacity;
};

type Me = { id: number; club: number | null };

export default function MatchListScreen() {
  const router = useRouter();
  const me = useQuery<Me, ApiError>({
    queryKey: ['me'],
    queryFn: () => apiGet<Me>('/me/'),
  });
  const clubId = me.data?.club ?? null;
  const matches = useQuery<Match[], ApiError>({
    queryKey: ['matches', clubId],
    queryFn: () => apiGet<Match[]>(`/clubs/${clubId}/matches/`),
    enabled: clubId != null,
  });

  if (matches.isLoading || me.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (matches.isError) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Error: {matches.error.message}</Text>
      </View>
    );
  }
  if (!matches.data || matches.data.length === 0) {
    return (
      <View style={styles.center}>
        <Text>No hay partidos disponibles</Text>
      </View>
    );
  }
  return (
    <ScrollView>
      {matches.data.map((m) => (
        <MatchCard
          key={m.id}
          match={m}
          onPress={() => router.push(`/(app)/matches/${m.id}`)}
        />
      ))}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  error: { color: '#c00' },
});
