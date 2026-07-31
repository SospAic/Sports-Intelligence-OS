export function isEventScoreAvailable(
  metadata: Record<string, unknown>,
  key: "controversy_score" | "visual_score" | "story_score",
): boolean {
  const availability = metadata.score_availability;
  return (
    typeof availability === "object" &&
    availability !== null &&
    (availability as Record<string, unknown>)[key] === true
  );
}

export function eventRecommendationScore(
  metadata: Record<string, unknown>,
): number | null {
  const value = metadata.recommendation_score;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
