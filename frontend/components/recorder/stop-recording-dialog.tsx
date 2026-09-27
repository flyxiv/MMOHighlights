"use client";

import { toast } from "sonner";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import { buttonVariants } from "@/components/ui/button";
import { errorMessage } from "@/lib/api";
import { formatDuration, recordingElapsed } from "@/lib/format";
import { useStopRecording } from "@/lib/queries";
import type { RecordingOut } from "@/lib/types";
import { useNow } from "@/lib/use-now";

export function StopRecordingDialog({
  recording,
  onOpenChange,
}: {
  recording: RecordingOut | null;
  onOpenChange: (open: boolean) => void;
}) {
  const stop = useStopRecording();
  const now = useNow();

  const confirm = (e: React.MouseEvent) => {
    e.preventDefault();
    if (!recording) return;
    stop.mutate(recording.id, {
      onSuccess: () => {
        toast.success(`Stopping ${recording.channel.display_name}`, {
          description: "Closing the current segment and uploading what was captured.",
        });
        onOpenChange(false);
      },
      onError: (err) => toast.error("Couldn't stop the recording", { description: errorMessage(err) }),
    });
  };

  return (
    <AlertDialog open={!!recording} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Stop recording {recording?.channel.display_name}?</AlertDialogTitle>
          <AlertDialogDescription>
            The stream keeps going, but the recorder closes the current segment and uploads what has been
            captured
            {recording && now ? (
              <span className="font-mono tabular-nums">
                {" "}
                ({formatDuration(recordingElapsed(recording, now))} so far)
              </span>
            ) : null}
            .
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={stop.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={buttonVariants({ variant: "destructive" })}
            disabled={stop.isPending}
            onClick={confirm}
          >
            Stop recording
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
