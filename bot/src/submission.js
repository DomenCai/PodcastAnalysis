export async function finishAndPresent(ledger, token, result, channel, messageId, chatId, card, text) {
  ledger.finishSubmission(token, result);
  try { await channel.updateCard(messageId, card); }
  catch { await channel.send(chatId, { text }); }
}
