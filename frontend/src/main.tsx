import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import "@/api/axiosClient";
import { AnalystWorkspaceProvider } from "./context/AnalystWorkspaceContext";
import { PageMetaProvider } from "./context/PageMetaContext";
import { TenantEnvironmentProvider } from "./context/TenantEnvironmentContext";
import { ThemeProvider } from "./context/ThemeContext";
import { ToastProvider } from "./context/ToastContext";
import { DataCachesProvider } from "./providers/DataCachesProvider";
import { GlobalErrorShell } from "./components/errors/GlobalErrorShell";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <GlobalErrorShell>
    <React.StrictMode>
      <ThemeProvider>
        <BrowserRouter>
          <AnalystWorkspaceProvider>
            <TenantEnvironmentProvider>
              <PageMetaProvider>
                <ToastProvider>
                  <DataCachesProvider>
                    <App />
                  </DataCachesProvider>
                </ToastProvider>
              </PageMetaProvider>
            </TenantEnvironmentProvider>
          </AnalystWorkspaceProvider>
        </BrowserRouter>
      </ThemeProvider>
    </React.StrictMode>
  </GlobalErrorShell>,
);
