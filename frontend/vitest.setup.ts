import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// Unmount whatever a component test rendered so the next one starts clean.
afterEach(() => {
  cleanup();
});
