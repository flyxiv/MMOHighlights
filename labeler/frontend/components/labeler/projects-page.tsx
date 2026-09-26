"use client";

import Link from "next/link";
import { useState } from "react";
import { FolderOpenIcon, PlusIcon } from "lucide-react";
import { NewProjectDialog } from "@/components/labeler/new-project-dialog";
import { Brand } from "@/components/labeler/top-bar";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { errorMessage } from "@/lib/api";
import { formatNumber, tasksLabel } from "@/lib/format";
import { useHealth, useProjects } from "@/lib/queries";

const dateFmt = new Intl.DateTimeFormat("en-US", { month: "short", day: "numeric", year: "numeric" });

export function ProjectsPage() {
  const { data: projects, error, isLoading } = useProjects();
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
              Classification, boxes and polygons. Each project is a folder in{" "}
              <span className="font-mono">{health?.storage ?? "the bucket"}</span>.
            </p>
          </div>
          <Button onClick={() => setOpen(true)}>
            <PlusIcon />
            New project
          </Button>
        </div>

        <div className="overflow-hidden rounded-lg border bg-card shadow-xs">
          {isLoading ? (
            <div className="flex flex-col gap-2 p-4">
              <Skeleton className="h-12" />
              <Skeleton className="h-12" />
            </div>
          ) : error ? (
            <p className="p-6 text-sm text-danger">
              Couldn&apos;t list projects: {errorMessage(error)}
            </p>
          ) : !projects?.length ? (
            <div className="flex flex-col items-center gap-3 p-12 text-center">
              <FolderOpenIcon className="size-8 text-muted-foreground" />
              <div>
                <p className="font-medium">No projects yet</p>
                <p className="text-sm text-muted-foreground">Create one and point it at a folder of frames.</p>
              </div>
              <Button variant="outline" onClick={() => setOpen(true)}>
                <PlusIcon />
                New project
              </Button>
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="border-b text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Project</th>
                  <th className="px-4 py-2.5 font-medium">Tasks</th>
                  <th className="px-4 py-2.5 text-right font-medium">Images</th>
                  <th className="px-4 py-2.5 font-medium">Progress</th>
                  <th className="px-4 py-2.5 font-medium">Created</th>
                </tr>
              </thead>
              <tbody>
                {projects.map((p) => {
                  const pct = p.done !== null && p.image_count ? Math.round((p.done / p.image_count) * 100) : null;
                  return (
                    <tr key={p.slug} className="relative border-b last:border-0 hover:bg-accent/50">
                      <td className="px-4 py-3">
                        <Link href={`/p/${p.slug}`} className="font-medium after:absolute after:inset-0">
                          {p.name}
                        </Link>
                        <div className="font-mono text-xs text-muted-foreground">{p.slug}/</div>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {tasksLabel(p.tasks)}
                        {p.classes ? ` · ${p.classes} classes` : ""}
                      </td>
                      <td className="px-4 py-3 text-right font-mono tnum">{formatNumber(p.image_count)}</td>
                      <td className="px-4 py-3">
                        {pct === null ? (
                          <span className="text-xs text-muted-foreground">Open to load</span>
                        ) : (
                          <span className="flex items-center gap-2 text-xs text-muted-foreground tnum">
                            <span className="h-1.5 w-24 overflow-hidden rounded-full bg-muted">
                              <span className="block h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                            </span>
                            {pct}%
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">{dateFmt.format(new Date(p.created_at))}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>
      </main>
      <NewProjectDialog open={open} onOpenChange={setOpen} />
    </div>
  );
}
