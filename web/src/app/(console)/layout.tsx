import { AppSidebar } from "@/components/console/app-sidebar";
import { ConsoleToolbar } from "@/components/console/toolbar";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";

export default function ConsoleLayout({ children }: { children: React.ReactNode }) {
  return (
    <SidebarProvider>
      <AppSidebar />
      <SidebarInset className="bg-secondary/60 dark:bg-background">
        <ConsoleToolbar />
        <main className="flex-1">{children}</main>
      </SidebarInset>
    </SidebarProvider>
  );
}
