import type { Metadata } from "next";
import { Inter } from "next/font/google";
import { ThemeProvider } from "next-themes";
import AppShell from "@/components/AppShell";
import { OperatorProvider } from "@/components/OperatorAccess";
import "./globals.css";

const inter = Inter({ variable: "--font-inter", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "Awareness Gap Miner", template: "%s · Awareness Gap Miner" },
  description:
    "Collects public text about Indian government welfare schemes and surfaces recurring awareness-gap signals with traceable NLP.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" suppressHydrationWarning className={inter.variable}>
      <body className="min-h-screen font-sans">
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          <OperatorProvider>
            <AppShell>{children}</AppShell>
          </OperatorProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
