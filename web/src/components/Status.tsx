import type { JobStatus, SubscriptionEpisodeStatus } from "../lib/types";
import { statusLabel } from "../lib/format";

export function StatusBadge({
  status,
}: {
  status: JobStatus | SubscriptionEpisodeStatus;
}) {
  const tone =
    status === "done"
      ? "success"
      : status === "error" || status === "failed"
        ? "danger"
        : status === "awaiting"
          ? "warning"
          : status === "running" ||
            status === "processing" ||
            status === "queued" ||
            status === "pending"
          ? "info"
          : "neutral";
  return (
    <span className={`badge ${tone}`}>
      <i />
      {statusLabel(status)}
    </span>
  );
}
