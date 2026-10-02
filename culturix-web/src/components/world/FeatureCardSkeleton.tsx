export default function FeatureCardSkeleton() {
  return (
    <div aria-hidden="true" className="rounded-2xl border border-gray-100 overflow-hidden bg-white">
      <div className="aspect-[9/16] bg-gray-100 animate-pulse motion-reduce:animate-none" />
      <div className="p-3 sm:p-4 space-y-2">
        <div className="h-3.5 w-4/5 rounded bg-gray-100 animate-pulse motion-reduce:animate-none" />
        <div className="h-3 w-1/2 rounded bg-gray-100 animate-pulse motion-reduce:animate-none" />
      </div>
    </div>
  );
}
