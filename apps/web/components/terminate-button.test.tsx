// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TerminateButton } from "./terminate-button";

afterEach(() => {
  vi.useRealTimers();
});

describe("TerminateButton", () => {
  it("shows the default label and arms on first click", async () => {
    const onTerminate = vi.fn();
    render(<TerminateButton onTerminate={onTerminate} />);
    expect(screen.getByRole("button", { name: /终止任务/ })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: /终止任务/ }));
    expect(screen.getByRole("button", { name: /确认终止/ })).toBeTruthy();
    expect(onTerminate).not.toHaveBeenCalled();
  });

  it("calls onTerminate only after the second (confirm) click", async () => {
    const onTerminate = vi.fn();
    render(<TerminateButton onTerminate={onTerminate} />);

    await userEvent.click(screen.getByRole("button", { name: /终止任务/ }));
    await userEvent.click(screen.getByRole("button", { name: /确认终止/ }));

    expect(onTerminate).toHaveBeenCalledTimes(1);
  });

  it("is disabled and shows progress while busy", () => {
    render(<TerminateButton onTerminate={vi.fn()} busy />);
    const button = screen.getByRole("button", { name: /终止中/ });
    expect(button).toBeTruthy();
    expect(button.hasAttribute("disabled")).toBe(true);
  });

  it("is disabled when the disabled prop is set", () => {
    render(<TerminateButton onTerminate={vi.fn()} disabled />);
    expect(
      screen.getByRole("button", { name: /终止任务/ }).hasAttribute("disabled"),
    ).toBe(true);
  });
});
