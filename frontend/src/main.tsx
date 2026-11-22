import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import { EstateProvider } from "./lib/estate";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <EstateProvider>
        <App />
      </EstateProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
