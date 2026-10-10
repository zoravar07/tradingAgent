import { Dialog } from "@base-ui-components/react/dialog";
import { X } from "@phosphor-icons/react";
import type { ReactNode } from "react";

/**
 * Right-side drawer for long-form analysis. Built on base-ui's Dialog rather
 * than a hand-rolled <div> so focus trapping, escape-to-dismiss, scroll
 * locking, and aria wiring are real — `pick-ui-library` names a div-based
 * dialog with manual focus handling as a mismatch to catch.
 *
 * Why a sheet and not more inline text: a full thesis paragraph inline pushes
 * every following card below the fold, so the list stops being scannable. The
 * card shows one plain-English sentence; the argument lives here.
 *
 * Motion: enters and exits through the same edge (`animate` — exit the way it
 * entered), 300ms on --ease-drawer, which is the drawer curve and sits at the
 * top of the 200-500ms drawer budget. transform + opacity only.
 */
export function Sheet({
  open,
  onOpenChange,
  title,
  eyebrow,
  children,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  eyebrow?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-40 bg-surface-0/70 backdrop-blur-[2px] transition-opacity duration-[var(--dur-sheet)] ease-out data-[ending-style]:opacity-0 data-[starting-style]:opacity-0" />
        <Dialog.Popup className="fixed inset-y-0 right-0 z-50 flex w-full max-w-[30rem] flex-col border-l border-line bg-surface-1 transition-transform duration-[var(--dur-sheet)] ease-[var(--ease-drawer)] data-[ending-style]:translate-x-full data-[starting-style]:translate-x-full">
          <header className="flex items-start justify-between gap-sp-3 border-b border-line px-sp-5 py-sp-4">
            <div className="min-w-0">
              {eyebrow && <div className="mb-sp-1 flex items-center gap-sp-2">{eyebrow}</div>}
              <Dialog.Title className="t-title text-ink">{title}</Dialog.Title>
            </div>
            <Dialog.Close
              aria-label="Close"
              className="pressable -mr-sp-1 -mt-sp-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-inner text-ink-faint hover:bg-surface-2 hover:text-ink"
            >
              <X size={14} weight="bold" />
            </Dialog.Close>
          </header>

          <div className="flex-1 overflow-y-auto px-sp-5 py-sp-4">{children}</div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** A titled block inside a sheet — the unit long-form analysis is built from. */
export function SheetSection({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section className="mb-sp-5 last:mb-0">
      <h3 className="t-label mb-sp-2 text-ink-faint">{label}</h3>
      <div className="t-body text-ink-dim">{children}</div>
    </section>
  );
}
