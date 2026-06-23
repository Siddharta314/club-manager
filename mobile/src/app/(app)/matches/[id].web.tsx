import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams, useRouter } from 'expo-router';
import {
  ActivityIndicator,
  Alert,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

import { apiGet, apiPost, ApiError } from '@/lib/api';

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

export default function MatchDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const router = useRouter();
  const queryClient = useQueryClient();

  const me = useQuery<Me, ApiError>({ queryKey: ['me'], queryFn: () => apiGet<Me>('/me/') });
  const clubId = me.data?.club ?? null;
  const match = useQuery<Match, ApiError>({
    queryKey: ['match', id],
    queryFn: () => apiGet<Match>(`/matches/${id}/`),
    enabled: id != null,
  });

  const signup = useMutation<Match, ApiError, void>({
    mutationFn: () => apiPost<Match, {}>(`/matches/${id}/join/`, {}),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['matches', clubId] });
      queryClient.invalidateQueries({ queryKey: ['match', id] });
    },
    onError: (err) => Alert.alert('No se pudo inscribir', err.message),
  });

  if (match.isLoading || me.isLoading) {
    return <View style={styles.center}><ActivityIndicator /></View>;
  }
  if (match.isError) {
    return <View style={styles.center}><Text style={styles.error}>Error: {match.error.message}</Text></View>;
  }
  if (!match.data) {
    return <View style={styles.center}><Text>Partido no encontrado</Text></View>;
  }
  const m = match.data;
  const isHost = m.players.some((p) => p.is_host && p.user_id === me.data?.id);
  const isPlayer = m.players.some((p) => !p.is_host && p.user_id === me.data?.id);
  const isOpen = m.capacity.is_open;
  const isCancelled = m.is_cancelled;

  let buttonLabel = 'Unirme';
  let disabled = false;
  if (signup.isPending) { buttonLabel = 'Inscribiendo...'; disabled = true; }
  else if (signup.isSuccess) { buttonLabel = 'Inscrito'; disabled = true; }
  else if (isHost) { buttonLabel = 'Eres el host'; disabled = true; }
  else if (isPlayer) { buttonLabel = 'Ya estás inscrito'; disabled = true; }
  else if (isCancelled) { buttonLabel = 'Partido cancelado'; disabled = true; }
  else if (!isOpen) { buttonLabel = 'Partido completo'; disabled = true; }

  return (
    <ScrollView>
      <View style={styles.header}>
        <Text style={styles.time}>{new Date(m.start_time).toLocaleString()}</Text>
        <Text style={styles.court}>{m.court.name}</Text>
        <Text style={styles.level}>Nivel {m.level_min}–{m.level_max}</Text>
        <Text style={styles.joined}>{m.capacity.player_count}/{m.capacity.total} jugadores</Text>
      </View>

      <View style={styles.section}>
        <Text style={styles.sectionTitle}>Jugadores inscritos</Text>
        {m.players.map((p) => (
          <Text key={p.user_id} style={styles.player}>
            {p.user_name} (nivel {p.user_level}){p.is_host ? ' — host' : ''}
          </Text>
        ))}
      </View>

      <Pressable
        style={[styles.button, disabled && styles.buttonDisabled]}
        onPress={() => signup.mutate()}
        disabled={disabled}
      >
        {signup.isPending
          ? <ActivityIndicator color="#fff" />
          : <Text style={styles.buttonText}>{buttonLabel}</Text>}
      </Pressable>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: 'center', alignItems: 'center', padding: 20 },
  error: { color: '#c00' },
  header: { padding: 20, borderBottomWidth: 1, borderBottomColor: '#eee' },
  time: { fontSize: 14, color: '#666' },
  court: { fontSize: 22, fontWeight: '700', marginTop: 4 },
  level: { fontSize: 16, marginTop: 8 },
  joined: { fontSize: 14, marginTop: 4 },
  section: { padding: 20, borderBottomWidth: 1, borderBottomColor: '#eee' },
  sectionTitle: { fontSize: 16, fontWeight: '600', marginBottom: 8 },
  player: { fontSize: 14, marginVertical: 2 },
  button: {
    margin: 20,
    padding: 14,
    backgroundColor: '#0a7',
    borderRadius: 8,
    alignItems: 'center',
  },
  buttonDisabled: { backgroundColor: '#999' },
  buttonText: { color: '#fff', fontSize: 16, fontWeight: '600' },
});
