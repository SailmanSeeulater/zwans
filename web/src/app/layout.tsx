import type { Metadata } from "next";
import { Suspense } from "react";
import { Palette } from "@/components/Palette";
import { Sidebar } from "@/components/Sidebar";
import { THEME_SCRIPT } from "@/lib/theme";
import "./globals.css";

export const metadata: Metadata = {
  title: "Zwans",
  description: "Sessions and evals for Zwans, a coding agent built from scratch.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // The theme script sets data-theme before React hydrates.
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} />
      </head>
      <body>
        <div className="wallpaper" aria-hidden="true" />
        <div className="shell">
          {/* useSearchParams needs a Suspense boundary in a static export. */}
          <Suspense>
            <Sidebar />
          </Suspense>
          <div className="shell-main">{children}</div>
        </div>
        <Suspense>
          <Palette />
        </Suspense>
      </body>
    </html>
  );
}
