// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ThemeToggle } from "./theme-toggle";

describe("ThemeToggle", () => {
  beforeEach(() => {
    document.documentElement.setAttribute("data-theme", "dark");
    window.localStorage.clear();
  });

  it("changes the document theme and accessible label when clicked", async () => {
    render(<ThemeToggle />);

    await userEvent.click(screen.getByRole("button", { name: "切换到浅色主题" }));

    expect(document.documentElement.getAttribute("data-theme")).toBe("light");
    expect(screen.getByRole("button", { name: "切换到深色主题" })).toBeTruthy();
    expect(window.localStorage.getItem("sio-theme")).toBe("light");
  });
});
