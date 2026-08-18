import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { LanguageSwitcher } from "@/components/language-switcher";
import { UiLanguageProvider } from "@/lib/ui-i18n";

describe("LanguageSwitcher", () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it("changes rendered interface chrome instead of only changing html lang", () => {
    render(
      <UiLanguageProvider>
        <LanguageSwitcher />
      </UiLanguageProvider>,
    );

    expect(screen.getByRole("button", { name: "界面语言" })).toHaveTextContent(
      "简体中文",
    );
    fireEvent.click(screen.getByRole("button", { name: "界面语言" }));
    fireEvent.click(screen.getByRole("option", { name: /英语/ }));

    expect(
      screen.getByRole("button", { name: "Interface language" }),
    ).toHaveTextContent("English");
    expect(document.documentElement.lang).toBe("en-US");
    expect(document.documentElement.dataset.uiLanguage).toBe("en-US");
  });
});
