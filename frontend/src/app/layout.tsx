import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Script from "next/script";
import { Toaster } from "sonner";
import { Providers } from "@/components/providers";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { ConfirmDialogHost } from "@/components/ui/confirm-dialog";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "Budget Pet - Family Budget Manager",
  description: "Track spending, accounts, and savings goals for your whole family",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "Budget Pet",
  },
  formatDetection: {
    telephone: false,
  },
  manifest: "/manifest.webmanifest",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#059669" },
    { media: "(prefers-color-scheme: dark)",  color: "#064e3b" },
  ],
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" className="dark">
      <head>
        {/* Telegram WebApp SDK — required so window.Telegram.WebApp exists
            when the page is opened from the bot's MenuButton. afterInteractive
            (not beforeInteractive) because the SDK writes --tg-viewport-* CSS
            vars onto <html> as soon as it loads; running before hydration
            causes a server/client style mismatch warning in normal browsers.
            All consumers read window.Telegram lazily from effects, so deferring
            past hydration is safe. */}
        <Script
          src="https://telegram.org/js/telegram-web-app.js"
          strategy="afterInteractive"
        />
      </head>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground app-noise`}
      >
        <Providers>
          <ProtectedRoute>
            {children}
          </ProtectedRoute>
          <ConfirmDialogHost />
          <Toaster position="top-right" richColors closeButton theme="dark" />
        </Providers>
      </body>
    </html>
  );
}
