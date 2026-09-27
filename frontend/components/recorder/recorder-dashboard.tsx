"use client";

import { useState } from "react";
import { useLiveEvents } from "@/lib/events";
import { ChannelsCard } from "./channels-card";
import { CompletedCard } from "./completed-card";
import { RecordingSheet } from "./recording-sheet";
import { RecordingsCard } from "./recordings-card";
import { StatCards } from "./stat-cards";
import { TopBar } from "./top-bar";

export function RecorderDashboard() {
  const connection = useLiveEvents();
  const [sheetId, setSheetId] = useState<string | null>(null);
  const [sheetOpen, setSheetOpen] = useState(false);

  const openRecording = (id: string) => {
    setSheetId(id);
    setSheetOpen(true);
  };

  return (
    <div className="min-h-dvh">
      <TopBar connection={connection} />
      <main className="mx-auto max-w-[1440px] space-y-6 px-4 pt-8 pb-16 sm:px-6 lg:px-12 lg:pt-10">
        <div className="space-y-1.5">
          <h1 className="text-2xl font-semibold tracking-tight">Live Recorder</h1>
          <p className="text-sm text-muted-foreground">
            Checks tracked channels every 30 seconds and starts recording the moment a stream goes live.
          </p>
        </div>
        <StatCards />
        <ChannelsCard onOpenRecording={openRecording} />
        <RecordingsCard onOpenRecording={openRecording} />
        <CompletedCard onOpenRecording={openRecording} />
      </main>
      <RecordingSheet recordingId={sheetId} open={sheetOpen} onOpenChange={setSheetOpen} />
    </div>
  );
}
