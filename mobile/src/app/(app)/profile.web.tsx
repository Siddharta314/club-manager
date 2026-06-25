import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "expo-router";
import { ActivityIndicator, Pressable, StyleSheet, Switch, Text, View } from "react-native";

import { apiGet, apiPatch, ApiError } from "@/lib/api";

type Me = {
  id: number;
  email: string;
  first_name: string;
  last_name: string;
  level: number;
  club: number | null;
  role: string;
  notify_push: boolean;
  notify_email: boolean;
};

// Wire shape: LevelField is a DecimalField — DRF serializes as string (e.g., "3.50").
// We cast to Me at the fetch site so the rest of the app sees a number.
type MeRaw = Omit<Me, "level"> & { level: string };

const ROLE_LABELS: Record<string, string> = {
  player: "Jugador",
  club_admin: "Admin de club",
  super_admin: "Super admin",
};

export default function ProfileScreen() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const me = useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: async () => {
      const raw = await apiGet<MeRaw>("/me/");
      return { ...raw, level: parseFloat(raw.level) || 0 };
    },
  });

  const updateNotifications = useMutation<
    { notify_push: boolean; notify_email: boolean },
    ApiError,
    { notify_push?: boolean; notify_email?: boolean }
  >({
    mutationFn: (updates) =>
      apiPatch<{ notify_push: boolean; notify_email: boolean }, { notify_push?: boolean; notify_email?: boolean }>(
        "/me/notifications/",
        {
          notify_push: updates.notify_push ?? me.data?.notify_push ?? true,
          notify_email: updates.notify_email ?? me.data?.notify_email ?? true,
        },
      ),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["me"] }),
  });

  if (me.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (me.isError) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Error: {me.error.message}</Text>
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

  const m = me.data;
  const firstName = m.first_name || m.email;
  const roleLabel = ROLE_LABELS[m.role] ?? m.role;
  const isClubAdmin = m.role === "club_admin";

  return (
    <View style={styles.container}>
      <Text style={styles.greeting}>Hola, {firstName}!</Text>
      <Text style={styles.label}>Email</Text>
      <Text style={styles.value}>{m.email}</Text>
      <Text style={styles.label}>Club</Text>
      <Text style={styles.value}>{m.club ? `Club #${m.club}` : "Sin club"}</Text>
      <Text style={styles.label}>Rol</Text>
      <Text style={styles.value}>{roleLabel}</Text>
      <Text style={styles.label}>Nivel {m.level}</Text>

      <View style={styles.toggleRow}>
        <Text>Notificaciones push</Text>
        <Switch
          value={m.notify_push}
          onValueChange={(v) => updateNotifications.mutate({ notify_push: v })}
          disabled={updateNotifications.isPending}
        />
      </View>
      <View style={styles.toggleRow}>
        <Text>Notificaciones email</Text>
        <Switch
          value={m.notify_email}
          onValueChange={(v) => updateNotifications.mutate({ notify_email: v })}
          disabled={updateNotifications.isPending}
        />
      </View>

      {isClubAdmin && (
        <Pressable
          style={styles.adminButton}
          onPress={() => router.push("/(app)/admin")}
        >
          <Text style={styles.adminButtonText}>Ver panel de administración</Text>
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, padding: 20 },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 20 },
  error: { color: "#c00" },
  greeting: { fontSize: 24, fontWeight: "700", marginBottom: 24 },
  label: { fontSize: 12, color: "#666", marginTop: 16, textTransform: "uppercase" },
  value: { fontSize: 16, marginTop: 4 },
  toggleRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: "#eee",
  },
  adminButton: {
    marginTop: 32,
    padding: 14,
    backgroundColor: "#1d4ed8",
    borderRadius: 8,
    alignItems: "center",
  },
  adminButtonText: { color: "#fff", fontSize: 16, fontWeight: "600" },
});