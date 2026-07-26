import { redirect } from "next/navigation";
import { getCurrentUser } from "@/lib/auth";
import { AutomationEditor } from "../automation-editor";
export default async function NewAutomationPage() {
  if (!(await getCurrentUser())) redirect("/login");
  return <AutomationEditor />;
}
