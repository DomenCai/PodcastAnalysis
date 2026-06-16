export function LoadingState({ label = "加载中" }: { label?: string }) {
  return (
    <div className="panel p-5 text-sm text-muted">
      {label}
    </div>
  );
}
