"use client";

import Link from "next/link";
import { useState } from "react";
import { FolderOpenIcon, PlusIcon } from "lucide-react";
import { NewDatasetDialog } from "@/components/labeler/new-dataset-dialog";
import { Brand } from "@/components/labeler/top-bar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { formatNumber, TYPE_NAMES } from "@/lib/format";
import { useDatasets, useHealth } from "@/lib/queries";

export function DatasetsPage() {
  const { data: datasets, error, isLoading } = useDatasets();
  const { data: health } = useHealth();
  const [open, setOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <header className="flex h-14 items-center border-b px-6">
        <Brand />
      </header>
      <main className="mx-auto flex max-w-5xl flex-col gap-6 px-6 py-8">
        <div className="flex items-end justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold">Image Labeling</h1>
            <p className="text-sm text-muted-foreground">
              Datasets in <span className="font-mono">{health?.storage ?? "the bucket"}</span>. Labels are saved to each
              dataset&apos;s <span className="font-mono">labeling/</span> folder until you cut a release.
            </p>
          </div>
          <Button onClick={() => setOpen(true)}>
            <PlusIcon />
            New dataset
          </Button>
        </div>

        <div className="overflow-hidden rounded-lg border bg-card shadow-xs">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : error ? (
            <p className="p-6 text-sm text-danger">Couldn&apos;t list datasets: {errorMessage(error)}</p>
          ) : !datasets?.length ? (
            <div className="flex flex-col items-center gap-3 p-12 text-center">
              <FolderOpenIcon className="size-8 text-muted-foreground" />
              <div>
                <p className="font-medium">No datasets yet</p>
                <p className="text-sm text-muted-foreground">
                  Create one here, or migrate existing data into <span className="font-mono">datasets/</span>.
                </p>
              </div>
              <Button variant="outline" onClick={() => setOpen(true)}>
                <PlusIcon />
                New dataset
              </Button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Dataset</th>
                  <th className="px-4 py-2.5 font-medium">Tasks</th>
                  <th className="px-4 py-2.5 font-medium">Latest</th>
                  <th className="px-4 py-2.5 text-right font-medium">Samples</th>
                  <th className="px-4 py-2.5 font-medium">Labeling</th>
                </tr>
              </thead>
              <tbody>
                {datasets.map((d) => (
                  <tr key={d.name} className="relative border-b last:border-0 hover:bg-accent/50">
                    <td className="px-4 py-3">
                      <Link href={`/d/${d.name}`} className="font-medium after:absolute after:inset-0">
                        {d.title}
                      </Link>
                      <div className="font-mono text-xs text-muted-foreground">datasets/{d.name}/</div>
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {Object.entries(d.tasks)
                        .map(([t, s]) => `${t} (${TYPE_NAMES[s.type].toLowerCase()})`)
                        .join(", ") || "none"}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs">{d.latest ?? "—"}</td>
                    <td className="px-4 py-3 text-right font-mono tnum">
                      {d.samples !== null ? formatNumber(d.samples) : "—"}
                    </td>
                    <td className="px-4 py-3 text-xs text-muted-foreground">
                      {d.labeling ? "in progress" : "not started"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </main>
      <NewDatasetDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
