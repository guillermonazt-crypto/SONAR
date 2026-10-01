import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { initTheme } from "./utils/theme";
import "./styles.css";
initTheme();
createRoot(document.getElementById("root")).render(<App />);
