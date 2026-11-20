import React from "react";
import { createRoot } from "react-dom/client";
import "./style.css";

function App() {
  return (
    <main>
      <h1>Experiment platform</h1>
      <p>The project skeleton is running.</p>
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
