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
import { formatDuration, secondsBetween } from "@/lib/format";
import { useRemoveChannel } from "@/lib/queries";
import type { ChannelOut } from "@/lib/types";
import { useNow } from "@/lib/use-now";

export function RemoveChannelDialog({
  channel,
  recordingStartedAt,
  onOpenChange,
}: {
  channel: ChannelOut | null;
  /** Start of the channel's active recording, when it has one. */
  recordingStartedAt: string | null;
  onOpenChange: (open: boolean) => void;
}) {
  const remove = useRemoveChannel();
  const now = useNow();
  const recording = !!channel?.active_recording_id;
  const since = recordingStartedAt ?? channel?.live_started_at ?? null;

  const confirm = (e: React.MouseEvent) => {
    e.preventDefault();
    if (!channel) return;
    remove.mutate(
      { id: channel.id, stopRecording: recording },
      {
        onSuccess: () => {
          toast.success(`Removed ${channel.display_name}`, {
            description: recording ? "The recording was stopped and is uploading." : undefined,
          });
          onOpenChange(false);
        },
        onError: (err) => toast.error(`Couldn't remove ${channel.display_name}`, { description: errorMessage(err) }),
      },
    );
  };

  return (
    <AlertDialog open={!!channel} onOpenChange={onOpenChange}>
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>Remove {channel?.display_name}?</AlertDialogTitle>
          <AlertDialogDescription>
            {recording ? (
              <>
                This channel is recording right now. Removing it stops the recording, closes the current
                segment, and uploads what has been captured
                {since && now ? (
                  <span className="font-mono tabular-nums"> ({formatDuration(secondsBetween(since, now))} so far)</span>
                ) : null}
                . Past recordings stay in the bucket.
              </>
            ) : (
              <>It won&apos;t be checked for new streams anymore. Past recordings stay in the bucket.</>
            )}
          </AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel disabled={remove.isPending}>Cancel</AlertDialogCancel>
          <AlertDialogAction
            className={buttonVariants({ variant: "destructive" })}
            disabled={remove.isPending}
            onClick={confirm}
          >
            {recording ? "Stop recording and remove" : "Remove"}
          </AlertDialogAction>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
