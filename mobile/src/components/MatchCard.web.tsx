import { Pressable, StyleSheet, Text } from 'react-native';

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

type MatchCardProps = { match: Match; onPress: () => void };

export default function MatchCard({ match, onPress }: MatchCardProps) {
  const host = match.players.find((p) => p.is_host);
  const time = new Date(match.start_time).toLocaleString();
  return (
    <Pressable style={styles.card} onPress={onPress}>
      <Text style={styles.time}>{time}</Text>
      <Text style={styles.court}>{match.court.name}</Text>
      <Text style={styles.level}>Nivel {match.level_min}–{match.level_max}</Text>
      <Text style={styles.joined}>
        {match.capacity.player_count}/{match.capacity.total} jugadores
      </Text>
      {host && <Text style={styles.host}>Host: {host.user_name}</Text>}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { padding: 16, marginVertical: 6, marginHorizontal: 12, borderWidth: 1, borderColor: '#ddd', borderRadius: 8, backgroundColor: '#fff' },
  time: { fontSize: 14, color: '#666' },
  court: { fontSize: 18, fontWeight: '600', marginTop: 4 },
  level: { fontSize: 14, marginTop: 4 },
  joined: { fontSize: 14, marginTop: 4 },
  host: { fontSize: 13, color: '#666', marginTop: 6 },
});
