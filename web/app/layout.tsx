import "./globals.css";
import Shell from "./components/Shell";

export const metadata = { title: "ISMS-P 갭분석" };

// 저장된 테마를 그리기 전에 적용 (깜빡임 방지)
const themeScript = `try{var t=localStorage.getItem("gap.theme");if(t)document.documentElement.dataset.theme=t}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko" suppressHydrationWarning>
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="" />
        <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&display=swap" rel="stylesheet" />
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body><Shell>{children}</Shell></body>
    </html>
  );
}
