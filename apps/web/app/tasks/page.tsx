import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { TasksClient } from "./tasks-client";
export default async function TasksPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <TasksClient />;
}
