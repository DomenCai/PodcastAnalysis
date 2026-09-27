import fs from "node:fs";
import path from "node:path";
import { dataDir } from "./config.js";

const ledgerPath = path.join(dataDir, "ledger.json");

export class Ledger {
  constructor(file = ledgerPath) {
    this.path = file;
    this.state = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, "utf8")) : { events: {}, notifications: {}, submissions: {}, initialized: false };
    this.state.submissions ||= {};
  }

  save() {
    fs.mkdirSync(path.dirname(this.path), { recursive: true, mode: 0o700 });
    const temp = `${this.path}.${process.pid}.tmp`;
    fs.writeFileSync(temp, `${JSON.stringify(this.state)}\n`, { mode: 0o600 });
    fs.renameSync(temp, this.path);
  }

  claimEvent(key, ttlMs = 30 * 86400_000) {
    if (this.state.events[key] && Date.now() - this.state.events[key] < ttlMs) return false;
    this.state.events[key] = Date.now();
    const cutoff = Date.now() - 30 * 86400_000;
    for (const [old, at] of Object.entries(this.state.events)) if (at < cutoff) delete this.state.events[old];
    this.save();
    return true;
  }

  claimNotification(key) {
    if (this.state.notifications[key]) return false;
    this.state.notifications[key] = Date.now();
    this.save();
    return true;
  }

  claimSubmission(token) {
    const record = this.state.submissions[token];
    if (record?.status === "done" || (record?.status === "pending" && Date.now() - record.at < 120_000)) return false;
    this.state.submissions[token] = { status: "pending", at: Date.now() };
    this.save();
    return true;
  }

  finishSubmission(token, result) {
    this.state.submissions[token] = { status: "done", at: Date.now(), result };
    this.save();
  }

  failSubmission(token) {
    delete this.state.submissions[token];
    this.save();
  }

  seed(jobs) {
    if (this.state.initialized) return;
    for (const job of jobs) if (["done", "error"].includes(job.status)) this.state.notifications[`${job.id}:${job.status}:${job.updated_at}`] = Date.now();
    this.state.initialized = true;
    this.save();
  }

}
