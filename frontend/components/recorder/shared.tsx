"use client";

import { toast } from "sonner";
import { Skeleton } from "@/components/ui/skeleton";
import { TableCell, TableRow } from "@/components/ui/table";

export async function copyText(text: string, what: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success(`${what} copied`);
  } catch {
    toast.error(`Couldn't copy ${what.toLowerCase()}`);
  }
}

/**
 * True when a row click should open the row's detail: ignores clicks on interactive
 * children and on portalled content (menus, popovers) that bubble through React.
 */
export function isRowActivation(e: React.MouseEvent<HTMLElement>): boolean {
  const target = e.target as HTMLElement;
  if (!e.currentTarget.contains(target)) return false;
  return !target.closest("button, a, input, [role=menuitem], [data-no-row-click]");
}

export function SkeletonRows({ columns, rows = 3 }: { columns: number; rows?: number }) {
  return (
    <>
      {Array.from({ length: rows }, (_, r) => (
        <TableRow key={r} className="hover:bg-transparent">
          {Array.from({ length: columns }, (_, c) => (
            <TableCell key={c} className="py-4">
              {c === 0 ? (
                <div className="flex items-center gap-3">
                  <Skeleton className="size-7 rounded-full" />
                  <Skeleton className="h-4 w-28" />
                </div>
              ) : (
                <Skeleton className="h-4 w-full max-w-24" />
              )}
            </TableCell>
          ))}
        </TableRow>
      ))}
    </>
  );
}

export function EmptyState({
  icon,
  title,
  description,
}: {
  icon: React.ReactNode;
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed px-6 py-12 text-center">
      <div className="mb-1 flex size-10 items-center justify-center rounded-full bg-muted text-muted-foreground [&_svg]:size-5">
        {icon}
      </div>
      <p className="text-sm font-medium">{title}</p>
      <p className="max-w-sm text-sm text-muted-foreground">{description}</p>
    </div>
  );
}

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-10 text-center text-sm">
      <p className="font-medium">Couldn&apos;t load this list</p>
      <p className="text-muted-foreground">{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="text-sm font-medium underline underline-offset-4">
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Card header used by the three table cards. */
export function SectionHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-4 px-4 sm:px-6 lg:flex-row lg:items-start lg:justify-between">
      <div className="min-w-0 space-y-1.5">
        <h2 className="leading-none font-semibold">{title}</h2>
        <p className="text-sm text-muted-foreground">{description}</p>
      </div>
      {actions ? <div className="flex flex-wrap items-start gap-2">{actions}</div> : null}
    </div>
  );
}
