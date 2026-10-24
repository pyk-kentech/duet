import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { applyStoredTheme } from "./views/Settings";
import "./styles.css";
import "./workbench.css";
import "./ide.css";

applyStoredTheme();   // 시스템 / 밝게 / 어둡게 (설정 화면)

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
