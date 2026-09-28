"use client";

import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { api, errorMessage } from "@/lib/api";
import { useEditor } from "@/lib/editor-store";
import { formatNumber } from "@/lib/format";
import { queryKeys } from "@/lib/queries";
import type { Dataset } from "@/lib/types";

function Row({ label, value, hint }: { label: string; value: number | string; hint?: string }) {
  return (
    <div className="flex items-baseline gap-2 py-1 text-sm">
      <span className="flex-1">
        {label}
        {hint ? <span className="block text-xs text-muted-foreground">{hint}</span> : null}
      </span>
      <span className="font-mono tnum">{typeof value === "number" ? formatNumber(value) : value}</span>
    </div>
  );
}

/** Cuts releases/<next>/ from the base release plus labeling/ (spec section 5a). */
export function ReleaseDialog({
  dataset,
  open,
  onOpenChange,
  flush,
}: {
  dataset: Dataset;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  flush: () => Promise<void>;
}) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const { total, done, excluded, new: fresh, edited_not_done: pending } = dataset.stats;

  const cut = async () => {
    setBusy(true);
    try {
      await flush();
      const r = await api.cutRelease(dataset.name, notes.trim());
      toast.success(`Released ${r.version}: ${formatNumber(r.samples)} samples, ${formatNumber(r.reviewed)} reviewed`, {
        description: r.uri,
        duration: 15_000,
        action: { label: "Copy path", onClick: () => void navigator.clipboard.writeText(r.uri) },
      });
      for (const w of r.warnings.slice(0, 3)) toast.warning(w);
      setNotes("");
      onOpenChange(false);
      // The release becomes the new base. Refresh first, then reopen: excluded samples are gone now.
      qc.removeQueries({ queryKey: ["sample", dataset.name] });
      await Promise.all([
        qc.invalidateQueries({ queryKey: queryKeys.dataset(dataset.name) }),
        qc.invalidateQueries({ queryKey: queryKeys.samples(dataset.name) }),
        qc.invalidateQueries({ queryKey: queryKeys.datasets }),
      ]);
      const url = new URL(window.location.href);
      url.searchParams.delete("sample");
      window.history.replaceState(null, "", url);
      useEditor.setState({ file: null, doc: null });
    } catch (e) {
      toast.error(errorMessage(e), { duration: 15_000 });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Cut release {dataset.next_release}</DialogTitle>
          <DialogDescription>
            Writes <span className="font-mono">releases/{dataset.next_release}/</span> and points{" "}
            <span className="font-mono">latest</span> at it. Releases never change afterwards; later fixes go into the
            next one.
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col divide-y rounded-md border px-3">
          <Row label="Samples in the release" value={total - excluded} hint={dataset.base_release ? `base ${dataset.base_release} plus new images` : "first release"} />
          <Row label="Reviewed (done)" value={done} hint="their labels from here, marked meta.reviewed" />
          <Row label="Not done" value={total - excluded - done} hint="keep their released labels; new images go in unlabeled" />
          <Row label="New images" value={fresh} hint="added here since the base release" />
          <Row label="Excluded" value={excluded} hint="left out" />
        </div>
        {pending ? (
          <p className="rounded-md bg-warning-soft px-3 py-2 text-xs text-warning">
            {formatNumber(pending)} image{pending === 1 ? " has" : "s have"} edits but {pending === 1 ? "isn't" : "aren't"}{" "}
            marked done. Only done images carry their labels into a release; press D on them (or Done in the grid) first
            if they&apos;re finished.
          </p>
        ) : null}
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Notes for dataset.json (optional), e.g. relabeled cast bars"
          rows={2}
          className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50"
        />
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={cut} disabled={busy || total - excluded === 0}>
            {busy ? "Writing…" : `Cut ${dataset.next_release}`}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
