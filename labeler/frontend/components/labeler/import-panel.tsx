"use client";

import { useRef } from "react";
import { FolderIcon, UploadIcon } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";
import { formatNumber } from "@/lib/format";
import { uploadInBatches } from "@/lib/queries";
import { cn } from "@/lib/utils";

export type SourceKind = "folder" | "bucket" | "upload";

export interface ImportSource {
  kind: SourceKind;
  path: string;
  files: File[];
}

export const EMPTY_SOURCE: ImportSource = { kind: "folder", path: "", files: [] };

const IMAGE_RE = /\.(jpe?g|png|webp|bmp)$/i;

export function sourceReady(s: ImportSource): boolean {
  if (s.kind === "upload") return s.files.length > 0;
  if (s.kind === "bucket") return /^gs:\/\/[^/]+/.test(s.path.trim());
  return s.path.trim().length > 0;
}

/**
 * Starts the import. Folder and bucket imports run on the server (poll the project's imports);
 * uploads run here and resolve when done.
 */
export async function runImport(slug: string, s: ImportSource, onUploadProgress: (done: number, total: number) => void) {
  if (s.kind === "upload") return uploadInBatches(slug, s.files, onUploadProgress);
  await api.startImport(slug, s.path.trim());
  return null;
}

const TABS: { kind: SourceKind; label: string }[] = [
  { kind: "folder", label: "Folder on this PC" },
  { kind: "bucket", label: "Cloud Storage" },
  { kind: "upload", label: "Upload" },
];

export function ImportPanel({ value, onChange }: { value: ImportSource; onChange: (s: ImportSource) => void }) {
  const filesRef = useRef<HTMLInputElement>(null);
  const folderRef = useRef<HTMLInputElement>(null);
  const pick = (list: FileList | null) => {
    const files = Array.from(list ?? []).filter((f) => IMAGE_RE.test(f.name));
    onChange({ ...value, files });
  };
  return (
    <div className="flex flex-col gap-2">
      <div className="flex w-fit rounded-md bg-muted p-[3px]">
        {TABS.map((t) => (
          <button
            type="button"
            key={t.kind}
            onClick={() => onChange({ ...value, kind: t.kind })}
            className={cn(
              "rounded-sm px-2.5 py-1 text-xs text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50",
              value.kind === t.kind && "bg-background font-medium text-foreground shadow-xs",
            )}
          >
            {t.label}
          </button>
        ))}
      </div>
      {value.kind === "upload" ? (
        <div className="flex items-center gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => filesRef.current?.click()}>
            <UploadIcon />
            Choose images
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => folderRef.current?.click()}>
            <FolderIcon />
            Choose a folder
          </Button>
          <span className="text-xs text-muted-foreground">
            {value.files.length ? `${formatNumber(value.files.length)} images selected` : "JPG, PNG, WebP or BMP"}
          </span>
          <input ref={filesRef} type="file" multiple accept="image/*" hidden onChange={(e) => pick(e.target.files)} />
          <input
            ref={folderRef}
            type="file"
            hidden
            onChange={(e) => pick(e.target.files)}
            {...({ webkitdirectory: "", directory: "" } as Record<string, string>)}
          />
        </div>
      ) : (
        <Input
          value={value.path}
          onChange={(e) => onChange({ ...value, path: e.target.value })}
          placeholder={
            value.kind === "bucket" ? "gs://mmohighlights/frames/ffxiv/" : "C:\\Users\\Public\\frames\\kefka-prog"
          }
          className="font-mono text-xs"
        />
      )}
      <p className="text-xs text-muted-foreground">
        {value.kind === "folder"
          ? "Images in the folder and its subfolders are copied into the project in the bucket."
          : value.kind === "bucket"
            ? "Every image under this prefix is copied into the project. The backend's credentials need read access."
            : "Files are sent through the page; for thousands of images a folder import is faster."}
      </p>
    </div>
  );
}
