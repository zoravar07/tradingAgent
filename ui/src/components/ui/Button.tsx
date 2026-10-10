import { cva, type VariantProps } from "class-variance-authority";
import clsx from "clsx";
import { Link } from "react-router-dom";

/**
 * `.pressable` carries the press feedback (scale 0.98 / 120ms) and the
 * colour transitions, including `transform` — a `transition-colors` next to
 * an `active:scale` makes the scale snap with no transition at all.
 *
 * `outline` is the reference's "Review Position" button: an accent-colored
 * label in a hairline box on a tinted ground. It is the only button that
 * appears inside a Callout.
 */
const button = cva(
  "pressable inline-flex items-center justify-center gap-sp-2 rounded-inner font-medium whitespace-nowrap disabled:pointer-events-none disabled:opacity-40",
  {
    variants: {
      variant: {
        primary: "bg-accent text-white hover:bg-accent/90",
        secondary: "border border-line-strong bg-surface text-ink-dim hover:bg-inset hover:text-ink",
        outline: "border border-accent-line bg-surface text-accent hover:bg-accent-wash",
        ghost: "text-ink-faint hover:bg-inset-strong hover:text-ink",
        danger: "border border-line-strong bg-surface text-ink-faint hover:border-loss/40 hover:text-loss",
      },
      size: {
        sm: "px-sp-3 py-[6px] text-[13px]",
        md: "px-sp-4 py-sp-2 text-[14px]",
        lg: "px-sp-5 py-sp-3 text-[15px]",
      },
    },
    defaultVariants: { variant: "secondary", size: "sm" },
  },
);

export function Button({
  variant,
  size,
  className,
  ...rest
}: VariantProps<typeof button> & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return <button className={clsx(button({ variant, size }), className)} {...rest} />;
}

/**
 * The same visual treatment on a router link. A `<Link>` nested inside a
 * `<button>` is invalid HTML and breaks keyboard activation, so navigation
 * actions get this rather than a Button wrapping a Link.
 */
export function ButtonLink({
  variant,
  size,
  className,
  ...rest
}: VariantProps<typeof button> & React.ComponentProps<typeof Link>) {
  return <Link className={clsx(button({ variant, size }), className)} {...rest} />;
}
