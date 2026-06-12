import type { Metadata } from "next";
import { Noto_Sans_JP, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Shell } from "@/components/Shell";

const noto = Noto_Sans_JP({
  variable: "--font-noto",
  subsets: ["latin"],
  weight: ["400", "500", "700"],
});

const jb = JetBrains_Mono({
  variable: "--font-jb",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
});

export const metadata: Metadata = {
  title: "Orchestrator — Control Room",
  description: "AI マルチエージェント・オーケストレーター 操作コンソール",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ja" className={`${noto.variable} ${jb.variable} h-full antialiased`}>
      <body className="min-h-full">
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
