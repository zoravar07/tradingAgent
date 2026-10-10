function Bar({ w }: { w: string }) {
  return <div className={`h-3 ${w} animate-pulse rounded-chip bg-inset-strong`} />;
}

function CardSkeleton({ rows }: { rows: number }) {
  return (
    <div className="rounded-card border border-line bg-surface p-sp-6 shadow-card">
      <Bar w="w-36" />
      <div className="mt-sp-5 flex flex-col gap-sp-4">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-sp-5">
            <Bar w="w-20" />
            <Bar w="w-28" />
            <Bar w="w-24" />
            <Bar w="w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

/**
 * Shaped like the real layout rather than a generic spinner, so the page
 * doesn't visibly jump once data arrives.
 */
export function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-sp-5">
      <CardSkeleton rows={2} />
      <CardSkeleton rows={3} />
    </div>
  );
}
