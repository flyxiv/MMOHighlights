"use client";

import { Fragment } from "react";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Kbd } from "@/components/ui/kbd";
import { useEditor } from "@/lib/editor-store";

const GROUPS: [string, [string, string[][]][]][][] = [
  [
    [
      "Tools",
      [
        ["Select / move", [["V"]]],
        ["Draw box", [["B"]]],
        ["Draw polygon", [["P"]]],
        ["Pan", [["H"]]],
        ["Pan (hold)", [["Space"]]],
      ],
    ],
    [
      "View",
      [
        ["Zoom in / out", [["+"], ["−"]]],
        ["Fit image", [["0"]]],
        ["Show / hide objects", [["`"]]],
        ["Undo / redo", [["Ctrl", "Z"], ["Ctrl", "⇧", "Z"]]],
      ],
    ],
  ],
  [
    [
      "Labeling",
      [
        ["Set class (or next shape's class)", [["1–9"]]],
        ["Set image class / tag", [["Q–I"]]],
        ["Accept suggestions", [["Enter"]]],
        ["Delete object", [["Del"]]],
        ["Move object 1 px / 10 px", [["←↑→↓"], ["⇧", "←"]]],
        ["Next / previous object", [["Tab"], ["⇧", "Tab"]]],
        ["Copy previous image's objects", [["C"]]],
      ],
    ],
    [
      "Navigate",
      [
        ["Save & next", [["D"]]],
        ["Previous", [["A"]]],
        ["Flag for review", [["F"]]],
        ["Exclude from releases", [["X"]]],
        ["Grid view", [["G"]]],
        ["Search", [["/"]]],
      ],
    ],
  ],
];

export function ShortcutsDialog() {
  const open = useEditor((s) => s.shortcutsOpen);
  const setOpen = useEditor((s) => s.setShortcutsOpen);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>
            Every labeling action has a key. Hold Space to pan with any tool; scroll to zoom at the cursor.
          </DialogDescription>
        </DialogHeader>
        <div className="grid grid-cols-2 gap-8">
          {GROUPS.map((col, i) => (
            <div key={i} className="flex flex-col gap-4">
              {col.map(([title, rows]) => (
                <div key={title} className="flex flex-col gap-0.5">
                  <span className="pb-1 text-xs font-medium text-muted-foreground">{title}</span>
                  {rows.map(([label, combos]) => (
                    <div key={label} className="flex items-center gap-1 py-0.5 text-sm">
                      <span className="flex-1">{label}</span>
                      {combos.map((keys, j) => (
                        <Fragment key={j}>
                          {j > 0 ? <span className="px-0.5 text-xs text-muted-foreground">/</span> : null}
                          {keys.map((k) => (
                            <Kbd key={k}>{k}</Kbd>
                          ))}
                        </Fragment>
                      ))}
                    </div>
                  ))}
                </div>
              ))}
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
