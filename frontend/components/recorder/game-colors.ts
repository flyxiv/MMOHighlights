/** Tailwind background class for a game's dot. */
export function gameDotClass(name: string | undefined | null): string {
  if (!name) return "bg-muted-foreground";
  if (/wow|warcraft/i.test(name)) return "bg-game-wow";
  if (/ff\s*xiv|ff14|final fantasy/i.test(name)) return "bg-game-ffxiv";
  return "bg-muted-foreground";
}
