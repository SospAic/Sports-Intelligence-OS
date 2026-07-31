import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { TopicsClient } from "./topics-client";
export default async function TopicsPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <TopicsClient />;
}
