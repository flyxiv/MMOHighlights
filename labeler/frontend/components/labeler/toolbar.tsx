"use client";

import {
  HandIcon,
  ImageIcon,
  LayoutGridIcon,
  MaximizeIcon,
  MousePointer2Icon,
  PentagonIcon,
  Redo2Icon,
  SparklesIcon,
  SquareDashedIcon,
  Undo2Icon,
  ZoomInIcon,
  ZoomOutIcon,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import { Separator } from "@/components/ui/separator";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { useEditor, type Tool, type ViewMode } from "@/lib/editor-store";
import type { Project } from "@/lib/types";
import { cn } from "@/lib/utils";

function Tip({ label, keys, children }: { label: string; keys?: string[]; children: React.ReactNode }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent className="flex items-center gap-1.5">
        {label}
        {keys?.map((k) => (
          <Kbd key={k} className="border-background/20 bg-background/15 text-background">
            {k}
          </Kbd>
        ))}
      </TooltipContent>
    </Tooltip>
  );
}

export function ViewToggle({ value, onChange }: { value: ViewMode; onChange: (v: ViewMode) => void }) {
  const item = (mode: ViewMode, label: string, Icon: typeof ImageIcon) => (
    <Tip label={mode === "single" ? "Single image" : "Grid for bulk classification"} keys={["G"]}>
      <button
        onClick={() => onChange(mode)}
        aria-pressed={value === mode}
        className={cn(
          "inline-flex h-7 items-center gap-1.5 rounded-sm px-2 text-xs text-muted-foreground outline-none focus-visible:ring-[3px] focus-visible:ring-ring/50 [&_svg]:size-4",
          value === mode && "bg-background font-medium text-foreground shadow-xs",
        )}
      >
        <Icon />
        {label}
      </button>
    </Tip>
  );
  return (
    <div className="flex rounded-md bg-muted p-0.5">
      {item("single", "Single", ImageIcon)}
      {item("grid", "Grid", LayoutGridIcon)}
    </div>
  );
}

const TOOLS: { tool: Tool; label: string; key: string; Icon: typeof HandIcon; needs?: "detection" | "segmentation" }[] = [
  { tool: "select", label: "Select and move", key: "V", Icon: MousePointer2Icon },
  { tool: "box", label: "Box", key: "B", Icon: SquareDashedIcon, needs: "detection" },
  { tool: "polygon", label: "Polygon", key: "P", Icon: PentagonIcon, needs: "segmentation" },
  { tool: "pan", label: "Pan (or hold Space)", key: "H", Icon: HandIcon },
];

export function availableTools(project: Project): Tool[] {
  return TOOLS.filter((t) => !t.needs || project.tasks.includes(t.needs)).map((t) => t.tool);
}

export function Toolbar({
  project,
  onCopyPrevious,
  canCopyPrevious,
}: {
  project: Project;
  onCopyPrevious: () => void;
  canCopyPrevious: boolean;
}) {
  const tool = useEditor((s) => s.tool);
  const setTool = useEditor((s) => s.setTool);
  const canUndo = useEditor((s) => s.past.length > 0);
  const canRedo = useEditor((s) => s.future.length > 0);
  const scale = useEditor((s) => s.view.scale);
  const viewMode = useEditor((s) => s.viewMode);
  const setViewMode = useEditor((s) => s.setViewMode);
  const { undo, redo, zoomAt, requestFit } = useEditor.getState();
  const tools = availableTools(project);
  const hasShapes = project.tasks.includes("detection") || project.tasks.includes("segmentation");

  return (
    <div className="flex h-12 shrink-0 items-center gap-1 border-b px-3">
      <ViewToggle value={viewMode} onChange={setViewMode} />
      <Separator orientation="vertical" className="mx-2 h-5!" />
      {hasShapes ? (
        <>
          <div className="flex gap-0.5 rounded-md border p-0.5">
            {TOOLS.filter((t) => tools.includes(t.tool)).map(({ tool: t, label, key, Icon }) => (
              <Tip key={t} label={label} keys={[key]}>
                <button
                  onClick={() => setTool(t)}
                  aria-pressed={tool === t}
                  aria-label={label}
                  className={cn(
                    "inline-flex size-7 items-center justify-center rounded-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/50 [&_svg]:size-4",
                    tool === t && "bg-accent text-foreground ring-1 ring-border",
                  )}
                >
                  <Icon />
                </button>
              </Tip>
            ))}
          </div>
          <Separator orientation="vertical" className="mx-2 h-5!" />
        </>
      ) : null}
      <Tip label="Undo" keys={["Ctrl", "Z"]}>
        <Button variant="ghost" size="icon-sm" onClick={undo} disabled={!canUndo} aria-label="Undo">
          <Undo2Icon />
        </Button>
      </Tip>
      <Tip label="Redo" keys={["Ctrl", "Shift", "Z"]}>
        <Button variant="ghost" size="icon-sm" onClick={redo} disabled={!canRedo} aria-label="Redo">
          <Redo2Icon />
        </Button>
      </Tip>
      <Separator orientation="vertical" className="mx-2 h-5!" />
      <Tip label="Zoom out" keys={["−"]}>
        <Button variant="ghost" size="icon-sm" onClick={() => zoomAt(1 / 1.25)} aria-label="Zoom out">
          <ZoomOutIcon />
        </Button>
      </Tip>
      <span className="w-12 text-center font-mono text-xs tnum">{Math.round(scale * 100)}%</span>
      <Tip label="Zoom in" keys={["+"]}>
        <Button variant="ghost" size="icon-sm" onClick={() => zoomAt(1.25)} aria-label="Zoom in">
          <ZoomInIcon />
        </Button>
      </Tip>
      <Tip label="Fit image" keys={["0"]}>
        <Button variant="ghost" size="icon-sm" onClick={requestFit} aria-label="Fit image">
          <MaximizeIcon />
        </Button>
      </Tip>
      <div className="flex-1" />
      {hasShapes ? (
        <Tip label="Copy objects from the previous image" keys={["C"]}>
          <Button variant="ghost" size="sm" onClick={onCopyPrevious} disabled={!canCopyPrevious}>
            Copy previous
          </Button>
        </Tip>
      ) : null}
      <Tooltip>
        <TooltipTrigger asChild>
          {/* Disabled buttons don't fire pointer events, so the tooltip hangs off a wrapper. */}
          <span tabIndex={0}>
            <Button variant="outline" size="sm" disabled>
              <SparklesIcon />
              Pre-label
            </Button>
          </span>
        </TooltipTrigger>
        <TooltipContent className="max-w-xs">
          No model is connected yet. Predictions can be imported through POST /api/projects/{project.slug}/predictions and
          show up as dashed suggestions.
        </TooltipContent>
      </Tooltip>
    </div>
  );
}
