import type { Metadata } from "next";
import type { ReactNode } from "react";
import { StaffShell } from "@/components/app/space-shells";

export const metadata: Metadata = { title: { default: "Console staff", template: "%s · Console staff" } };

export default function StaffLayout({ children }: { children: ReactNode }) {
  return <StaffShell>{children}</StaffShell>;
}
