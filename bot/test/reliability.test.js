import assert from "node:assert/strict";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { Ledger } from "../src/ledger.js";
import { deliverNotification } from "../src/notifications.js";
import { allowedAction, allowedMessage } from "../src/auth.js";
import { finishAndPresent } from "../src/submission.js";

test("通知发送失败不确认，重试使用同一 uuid，成功和重启后不重复", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "podcast-bot-test-"));
  try {
    const file = path.join(dir, "ledger.json");
    const ledger = new Ledger(file);
    const calls = [];
    let fail = true;
    const channel = { rawClient: { im: { v1: { message: { create: async (request) => {
      calls.push(request);
      if (fail) throw new Error("network");
      return { code: 0, data: { message_id: "om_1" } };
    } } } } } };
    await assert.rejects(deliverNotification(channel, ledger, "owner", "job:done:time", { schema: "2.0" }), /network/);
    assert.equal(ledger.state.notifications["job:done:time"], undefined);
    fail = false;
    assert.equal(await deliverNotification(channel, ledger, "owner", "job:done:time", { schema: "2.0" }), true);
    assert.equal(calls[0].data.uuid, calls[1].data.uuid);
    assert.equal(await deliverNotification(channel, new Ledger(file), "owner", "job:done:time", { schema: "2.0" }), false);
    assert.equal(calls.length, 2);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("成功提交的 token 持久消费，卡片更新失败改发文字且不撤销", async () => {
  const dir = mkdtempSync(path.join(tmpdir(), "podcast-bot-test-"));
  try {
    const file = path.join(dir, "ledger.json");
    const ledger = new Ledger(file);
    assert.equal(ledger.claimSubmission("token"), true);
    const sent = [];
    await finishAndPresent(ledger, "token", "job-id", {
      updateCard: async () => { throw new Error("card update failed"); },
      send: async (_chat, payload) => { sent.push(payload.text); },
    }, "message", "chat", { schema: "2.0" }, "任务已创建");
    assert.deepEqual(sent, ["任务已创建"]);
    assert.equal(new Ledger(file).claimSubmission("token"), false);
    assert.equal(new Ledger(file).state.submissions.token.result, "job-id");
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("非 owner 消息和群卡片被拒绝", () => {
  assert.equal(allowedMessage({ chatType: "p2p", senderId: "other" }, "owner"), false);
  assert.equal(allowedMessage({ chatType: "group", senderId: "owner" }, "owner"), false);
  assert.equal(allowedAction({ operator: { openId: "owner" } }, "owner", "group"), false);
  assert.equal(allowedAction({ operator: { openId: "other" } }, "owner", "p2p"), false);
});

test("通知版本按稳定 updated_at 去重，重新分析后可再发", () => {
  const dir = mkdtempSync(path.join(tmpdir(), "podcast-bot-test-"));
  try {
    const file = path.join(dir, "ledger.json");
    const job = { id: "old", status: "done", updated_at: "stable-1" };
    const ledger = new Ledger(file);
    ledger.seed([job]);
    const restarted = new Ledger(file);
    assert.ok(restarted.state.notifications["old:done:stable-1"]);
    assert.equal(restarted.state.notifications["old:done:stable-2"], undefined);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
