export function ErrorState({ message }: { message: string }) {
  return (
    <div className="notice chip-danger p-5">
      {message}
    </div>
  );
}
