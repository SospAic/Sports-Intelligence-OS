import { redirect } from "next/navigation";

import { getCurrentUser } from "@/lib/auth";
import { VideoSearchClient } from "./video-search-client";

export default async function VideoSearchPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <VideoSearchClient />;
}
