import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ActivityIndicator, Alert, Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";
import { useState } from "react";

import { apiGet, apiPost, ApiError } from "@/lib/api";

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

type CourtBrief = { id: number; name: string };

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

type Me = { id: number; club: number | null; role: string };

export default function AdminScreen() {
  const queryClient = useQueryClient();
  const me = useQuery<Me, ApiError>({ queryKey: ["me"], queryFn: () => apiGet<Me>("/me/") });
  const clubId = me.data?.club ?? null;
  const isAdmin = me.data?.role === "club_admin";

  const matches = useQuery<Match[], ApiError>({
    queryKey: ["admin-matches", clubId],
    queryFn: () => apiGet<Match[]>(`/clubs/${clubId}/matches/`),
    enabled: clubId != null && isAdmin,
  });

  const cancel = useMutation<unknown, ApiError, number>({
    mutationFn: (matchId) => apiPost(`/matches/${matchId}/cancel/`, {}),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["admin-matches", clubId] }),
    onError: (err) => Alert.alert("No se pudo cancelar", err.message),
  });

  if (me.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (!me.data) {
    return (
      <View style={styles.center}>
        <Text>No se pudo cargar el perfil</Text>
      </View>
    );
  }
  if (!isAdmin) {
    return (
      <View style={styles.center}>
        <Text>No tienes permisos de administración</Text>
      </View>
    );
  }

  if (matches.isLoading) {
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
        <Text>No hay partidos abiertos en tu club</Text>
      </View>
    );
  }

  return (
    <ScrollView>
      {matches.data.map((m) => (
        <AdminMatchRow
          key={m.id}
          match={m}
          isCancelling={cancel.isPending && cancel.variables === m.id}
          onCancel={() => {
            Alert.alert(
              "Cancelar partido",
              "¿Confirmas que quieres cancelar este partido?",
              [
                { text: "No", style: "cancel" },
                { text: "Sí, cancelar", style: "destructive", onPress: () => cancel.mutate(m.id) },
              ],
            );
          }}
        />
      ))}
    </ScrollView>
  );
}

function AdminMatchRow({
  match,
  onCancel,
  isCancelling,
}: {
  match: Match;
  onCancel: () => void;
  isCancelling: boolean;
}) {
  const [userId, setUserId] = useState("");
  const queryClient = useQueryClient();
  const me = useQuery<Me, ApiError>({ queryKey: ["me"], queryFn: () => apiGet<Me>("/me/") });
  const clubId = me.data?.club ?? null;

  const addPlayer = useMutation<unknown, ApiError, void>({
    mutationFn: () =>
      apiPost(`/matches/${match.id}/override-add/`, { user_id: parseInt(userId, 10) }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["admin-matches", clubId] });
      setUserId("");
    },
    onError: (err) => Alert.alert("No se pudo añadir", err.message),
  });

  const parsedId = parseInt(userId, 10);
  const canSubmit = !isNaN(parsedId) && parsedId > 0 && !addPlayer.isPending;

  return (
    <View style={styles.row}>
      <Text style={styles.court}>{match.court.name} — {new Date(match.start_time).toLocaleString()}</Text>
      <Text style={styles.meta}>Nivel {match.level_min}–{match.level_max} · {match.capacity.player_count}/{match.capacity.total} jugadores</Text>

      <Pressable
        style={[styles.actionButton, styles.cancelButton, isCancelling && styles.disabled]}
        onPress={onCancel}
        disabled={isCancelling}
      >
        <Text style={styles.actionButtonText}>Cancelar partido</Text>
      </Pressable>

      <View style={styles.addPlayerRow}>
        <TextInput
          style={styles.userIdInput}
          placeholder="User ID (Django pk)"
          keyboardType="number-pad"
          value={userId}
          onChangeText={setUserId}
          editable={!addPlayer.isPending}
        />
        <Pressable
          style={[styles.actionButton, styles.addButton, !canSubmit && styles.disabled]}
          onPress={() => addPlayer.mutate()}
          disabled={!canSubmit}
        >
          <Text style={styles.actionButtonText}>Añadir</Text>
        </Pressable>
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 20 },
  error: { color: "#c00" },
  row: { padding: 16, borderBottomWidth: 1, borderBottomColor: "#eee" },
  court: { fontSize: 16, fontWeight: "600", marginBottom: 4 },
  meta: { fontSize: 13, color: "#666", marginBottom: 8 },
  actionButton: {
    padding: 10,
    borderRadius: 8,
    alignItems: "center",
    marginTop: 8,
  },
  cancelButton: { backgroundColor: "#c00" },
  addButton: { backgroundColor: "#0a7" },
  disabled: { opacity: 0.5 },
  actionButtonText: { color: "#fff", fontWeight: "600" },
  addPlayerRow: { flexDirection: "row", alignItems: "center", marginTop: 8 },
  userIdInput: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#ccc",
    borderRadius: 8,
    padding: 8,
    marginRight: 8,
  },
});