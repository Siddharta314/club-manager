import { StyleSheet, Text, View } from "react-native";

type ChatMessage = {
  id: number;
  match_id: number;
  author_user_id: number | null;
  author_companion_id: number | null;
  author_display_name: string;
  text: string;
  created_at: string;
};

type ChatBubbleProps = { message: ChatMessage; isOwn: boolean };

export default function ChatBubble({ message, isOwn }: ChatBubbleProps) {
  const time = new Date(message.created_at).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });
  return (
    <View style={[styles.bubble, isOwn ? styles.own : styles.other]}>
      <Text style={styles.author}>{message.author_display_name}</Text>
      <Text style={styles.text}>{message.text}</Text>
      <Text style={styles.time}>{time}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  bubble: {
    maxWidth: "80%",
    padding: 10,
    marginVertical: 4,
    marginHorizontal: 12,
    borderRadius: 12,
  },
  own: {
    alignSelf: "flex-end",
    backgroundColor: "#dcf8c6",
  },
  other: {
    alignSelf: "flex-start",
    backgroundColor: "#eee",
  },
  author: { fontSize: 11, color: "#666", fontWeight: "600" },
  text: { fontSize: 14, marginTop: 2 },
  time: { fontSize: 10, color: "#999", alignSelf: "flex-end", marginTop: 4 },
});