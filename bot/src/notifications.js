import { createHash } from "node:crypto";

export async function deliverNotification(channel, ledger, ownerOpenId, key, card) {
  if (ledger.state.notifications[key]) return false;
  const uuid = createHash("sha256").update(key).digest("hex").slice(0, 32);
  const result = await channel.rawClient.im.v1.message.create({
    params: { receive_id_type: "open_id" },
    data: { receive_id: ownerOpenId, msg_type: "interactive", content: JSON.stringify(card), uuid },
  });
  if (result.code !== 0 || !result.data?.message_id) throw new Error(`飞书消息发送失败，code=${result.code}`);
  ledger.claimNotification(key);
  return true;
}
