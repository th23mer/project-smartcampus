import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import type { ReactNode } from "react";
import { DevRoleSwitcher } from "@/components/app/dev-role-switcher";
import "./globals.css";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "SmartCampus AI", template: "%s · SmartCampus AI" },
  description: "Assistant d'orientation universitaire de l'IIT et de l'ISB (projet pédagogique, données fictives).",
};

/**
 * Racine : interface en français. `dir` est explicite pour préparer l'arabe (RTL) :
 * il suffira de le passer à "rtl" avec `lang="ar"`.
 */
export default function RootLayout({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <html lang="fr" dir="ltr">
      <body className={`${geistSans.variable} ${geistMono.variable} antialiased`}>
        {children}
        <DevRoleSwitcher />
      </body>
    </html>
  );
}
