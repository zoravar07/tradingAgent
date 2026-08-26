function Bar({ w }: { w: string }) {
  return <div className={`h-3 ${w} animate-pulse rounded bg-[var(--color-panel-raised)]`} />;
}

function SectionSkeleton({ rows }: { rows: number }) {
  return (
    <div className="rounded-xl border border-[var(--color-hairline)] p-4">
      <Bar w="w-32" />
      <div className="mt-4 flex flex-col gap-3">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            <Bar w="w-14" />
            <Bar w="w-24" />
            <Bar w="w-20" />
            <Bar w="w-16" />
          </div>
        ))}
      </div>
    </div>
  );
}

// Shaped like the real layout (§4.5) rather than a generic spinner: matches
// the Briefing screen's section rhythm so the page doesn't visibly jump
// once data arrives.
export function LoadingSkeleton() {
  return (
    <div className="flex flex-col gap-5 px-8 py-6">
      <SectionSkeleton rows={2} />
      <SectionSkeleton rows={2} />
      <SectionSkeleton rows={3} />
    </div>
  );
}
