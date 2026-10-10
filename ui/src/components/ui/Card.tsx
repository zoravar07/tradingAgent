import { cva, type VariantProps } from "class-variance-authority";
import clsx from "clsx";
import type { ReactNode } from "react";

/**
 * The one card. Trade, Position, Order, Insight and Journal
 * entries are compositions of this — not six card implementations.
 *
 * `tone` paints a full-height accent stripe down the left edge, which is the
 * reference's single strongest card signal: you read the stripe before you
 * read the ticker. The stripe is the *only* place the semantic color touches
 * the card body — a washed background would make the color decorative, and
 * on white it would also swamp the hairline the card is defined by.
 *
 * The stripe is drawn with a pseudo-element inset to the card's own radius
 * so its top and bottom corners follow the card's, rather than sitting as a
 * square bar against a rounded box.
 */
const card = cva(
  "relative flex flex-col rounded-card border border-line bg-surface shadow-card transition-[border-color,box-shadow] duration-[var(--dur-hover)]",
  {
    variants: {
      tone: {
        neutral: "",
        buy: "pl-[3px] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:rounded-l-card before:bg-gain",
        sell: "pl-[3px] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:rounded-l-card before:bg-loss",
        accent:
          "pl-[3px] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:rounded-l-card before:bg-accent",
        risk: "pl-[3px] before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:rounded-l-card before:bg-risk",
      },
      /**
       * Opt-in, and off by default: most of these cards are not clickable,
       * and a hover lift on a non-clickable card promises an affordance that
       * doesn't exist.
       */
      interactive: {
        true: "hover-raise cursor-pointer",
        false: "",
      },
    },
    defaultVariants: { tone: "neutral", interactive: false },
  },
);

export type CardTone = NonNullable<VariantProps<typeof card>["tone"]>;

export function Card({
  tone,
  interactive,
  className,
  children,
  ...rest
}: VariantProps<typeof card> & {
  className?: string;
  children: ReactNode;
} & React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div className={clsx(card({ tone, interactive }), className)} {...rest}>
      {children}
    </div>
  );
}

/** Identity row: leading mark + name, trailing control. Always the top of a card. */
export function CardHeader({
  children,
  trailing,
  className,
}: {
  children: ReactNode;
  trailing?: ReactNode;
  className?: string;
}) {
  return (
    <div className={clsx("flex items-start justify-between gap-sp-4 px-sp-6 pt-sp-5", className)}>
      <div className="flex min-w-0 flex-wrap items-center gap-sp-3">{children}</div>
      {trailing && <div className="shrink-0">{trailing}</div>}
    </div>
  );
}

export function CardBody({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={clsx("flex-1 px-sp-6 py-sp-4", className)}>{children}</div>;
}

/**
 * The reference's footer is a full-bleed inset strip, not a padded row with
 * a rule above it — the tinted band is what makes "View full rationale &
 * details" read as a control rather than another line of card content.
 */
export function CardFooter({
  children,
  className,
  inset = false,
}: {
  children: ReactNode;
  className?: string;
  inset?: boolean;
}) {
  return (
    <div
      className={clsx(
        "mt-auto border-t border-line",
        inset ? "overflow-hidden rounded-b-card bg-inset" : "px-sp-6 py-sp-3",
        className,
      )}
    >
      {children}
    </div>
  );
}
