import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/geist";
import "@fontsource-variable/geist-mono";
import App from "./App.jsx";
import "./styles/index.css";

const queryClient = new QueryClient({
  defaultOptions: {
    // retry a couple of times: a heavy write (reconcile) can briefly overlap with
    // refetches and cause a transient server socket blip that recovers on retry.
    queries: { refetchOnWindowFocus: false, retry: 2, retryDelay: 400, staleTime: 15_000 },
  },
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);
