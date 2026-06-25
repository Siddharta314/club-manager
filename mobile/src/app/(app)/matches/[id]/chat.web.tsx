import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useLocalSearchParams } from "expo-router";
import { useIsFocused } from "@react-navigation/native";
import { useState } from "react";
import {
  ActivityIndicator,
  Alert,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";

import { apiGet, apiPost, ApiError } from "@/lib/api";
import ChatBubble from "@/components/ChatBubble.web";

type ChatMessage = {
  id: number;
  match_id: number;
  author_user_id: number | null;
  author_companion_id: number | null;
  author_display_name: string;
  text: string;
  created_at: string;
};

type Me = { id: number; role: string };

export default function ChatScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const queryClient = useQueryClient();
  const isFocused = useIsFocused();
  const [input, setInput] = useState("");

  const me = useQuery<Me, ApiError>({
    queryKey: ["me"],
    queryFn: () => apiGet<Me>("/me/"),
  });

  const messages = useQuery<ChatMessage[], ApiError>({
    queryKey: ["chat", id],
    queryFn: () => apiGet<ChatMessage[]>(`/matches/${id}/messages/?since=0`),
    refetchInterval: isFocused ? 5000 : false,
  });

  type PostContext = { previous: ChatMessage[] };

  const post = useMutation<ChatMessage, ApiError, string, PostContext>({
    mutationFn: (text) =>
      apiPost<ChatMessage, { text: string }>(`/matches/${id}/messages/`, { text }),
    onMutate: async (text): Promise<PostContext> => {
      await queryClient.cancelQueries({ queryKey: ["chat", id] });
      const previous = queryClient.getQueryData<ChatMessage[]>(["chat", id]) ?? [];
      const optimistic: ChatMessage = {
        id: -Date.now(),
        match_id: Number(id),
        author_user_id: me.data?.id ?? null,
        author_companion_id: null,
        author_display_name: "Tú",
        text,
        created_at: new Date().toISOString(),
      };
      queryClient.setQueryData<ChatMessage[]>(["chat", id], [...previous, optimistic]);
      return { previous };
    },
    onError: (err, _text, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["chat", id], context.previous);
      }
      Alert.alert("No se pudo enviar", err.message);
    },
    onSettled: () => queryClient.invalidateQueries({ queryKey: ["chat", id] }),
  });

  // 401/403 → user is not a member of the match
  if (
    messages.isError &&
    (messages.error.status === 401 || messages.error.status === 403)
  ) {
    return (
      <View style={styles.center}>
        <Text>No tienes acceso a este chat</Text>
      </View>
    );
  }
  if (messages.isLoading || me.isLoading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator />
      </View>
    );
  }
  if (messages.isError) {
    return (
      <View style={styles.center}>
        <Text style={styles.error}>Error: {messages.error.message}</Text>
      </View>
    );
  }

  const myId = me.data?.id;
  const list = messages.data ?? [];

  return (
    <KeyboardAvoidingView
      behavior={Platform.OS === "ios" ? "padding" : undefined}
      style={styles.container}
    >
      <FlatList
        data={list}
        keyExtractor={(m) => String(m.id)}
        renderItem={({ item }) => (
          <ChatBubble
            message={item}
            isOwn={myId != null && item.author_user_id === myId}
          />
        )}
        contentContainerStyle={styles.list}
      />
      <View style={styles.inputRow}>
        <TextInput
          style={styles.input}
          placeholder="Escribe un mensaje..."
          value={input}
          onChangeText={setInput}
          editable={!post.isPending}
        />
        <Pressable
          style={[styles.sendButton, post.isPending && styles.sendButtonDisabled]}
          onPress={() => {
            const trimmed = input.trim();
            if (trimmed.length === 0 || post.isPending) return;
            post.mutate(trimmed);
            setInput("");
          }}
          disabled={post.isPending}
        >
          <Text style={styles.sendButtonText}>Enviar</Text>
        </Pressable>
      </View>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1 },
  center: { flex: 1, justifyContent: "center", alignItems: "center", padding: 20 },
  error: { color: "#c00" },
  list: { paddingVertical: 8 },
  inputRow: {
    flexDirection: "row",
    padding: 8,
    borderTopWidth: 1,
    borderTopColor: "#eee",
    backgroundColor: "#fff",
  },
  input: {
    flex: 1,
    borderWidth: 1,
    borderColor: "#ccc",
    borderRadius: 8,
    padding: 8,
    marginRight: 8,
  },
  sendButton: {
    backgroundColor: "#0a7",
    paddingHorizontal: 16,
    paddingVertical: 8,
    borderRadius: 8,
    justifyContent: "center",
  },
  sendButtonDisabled: { opacity: 0.5 },
  sendButtonText: { color: "#fff", fontWeight: "600" },
});