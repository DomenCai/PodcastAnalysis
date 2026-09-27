export function allowedMessage(msg, ownerOpenId) {
  return msg.chatType === "p2p" && msg.senderId === ownerOpenId;
}

export function allowedAction(evt, ownerOpenId, chatMode) {
  return evt.operator.openId === ownerOpenId && chatMode === "p2p";
}
