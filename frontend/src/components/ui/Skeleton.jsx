/**
 * Skeleton — shimmer placeholder for async content.
 */
export default function Skeleton({
  width = '100%',
  height = 12,
  radius = 'var(--radius-xs)',
  style,
  ...rest
}) {
  return (
    <span
      aria-hidden
      style={{
        display: 'inline-block',
        width,
        height,
        borderRadius: radius,
        background:
          'linear-gradient(90deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.10) 50%, rgba(255,255,255,0.04) 100%)',
        backgroundSize: '200% 100%',
        animation: 'shimmer 1.4s linear infinite',
        ...style,
      }}
      {...rest}
    />
  );
}

export function SkeletonRow({ lines = 3, gap = 'var(--space-2)' }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap }}>
      {Array.from({ length: lines }).map((_, i) => (
        <Skeleton
          key={i}
          height={12}
          width={`${75 + Math.floor(Math.random() * 20)}%`}
        />
      ))}
    </div>
  );
}
