import { stateStyle } from "@/lib/format";

export function StateDot({
  state,
  pulse = false,
  showLabel = true,
}: {
  state: string;
  pulse?: boolean;
  showLabel?: boolean;
}) {
  const style = stateStyle(state);
  return (
    <span className="inline-flex items-center gap-2">
      <span
        className={`h-2 w-2 rounded-full ${style.dot} ${pulse ? "animate-pulseSoft" : ""}`}
        aria-hidden
      />
      {showLabel && (
        <span className={`font-mono text-[11px] tracking-wider ${style.text}`}>
          {style.label}
        </span>
      )}
    </span>
  );
}
