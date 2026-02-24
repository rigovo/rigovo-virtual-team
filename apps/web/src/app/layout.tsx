import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'Rigovo Teams',
  description: 'Composable AI engineering team platform',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen antialiased">{children}</body>
    </html>
  );
}
