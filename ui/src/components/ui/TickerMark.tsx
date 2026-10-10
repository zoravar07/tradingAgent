import clsx from "clsx";

/**
 * The square mark that opens a trade or position card in the reference.
 *
 * The reference shows a real company logo. There is no logo source in this
 * app and no field in the database to hold one, so this renders a monogram
 * tile instead: the ticker's own first characters, on a dark ground, at the
 * same size and radius the logo occupied. It is a placeholder for a logo,
 * not a placeholder for data — the letters shown are the real ticker.
 */
export function TickerMark({
  ticker,
  size = "md",
  className,
}: {
  ticker: string;
  size?: "sm" | "md";
  className?: string;
}) {
  const letters = ticker.slice(0, 2).toUpperCase();
  return (
    <span
      aria-hidden
      className={clsx(
        "flex shrink-0 items-center justify-center rounded-inner bg-ink font-semibold tracking-tight text-canvas",
        size === "md" ? "h-14 w-14 text-[19px]" : "h-9 w-9 text-[13px]",
        className,
      )}
    >
      {letters}
    </span>
  );
}
