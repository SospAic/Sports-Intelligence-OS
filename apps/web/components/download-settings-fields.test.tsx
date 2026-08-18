import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_DOWNLOAD_SETTINGS,
  DownloadSettingsFields,
} from "@/components/download-settings-fields";

describe("DownloadSettingsFields", () => {
  it("uses the requested defaults and controlled format options", () => {
    const onChange = vi.fn();
    render(
      <DownloadSettingsFields
        value={DEFAULT_DOWNLOAD_SETTINGS}
        onChange={onChange}
      />,
    );

    expect(screen.getByRole("checkbox", { name: /^下载字幕/ })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: /^自动生成字幕/ })).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: /^抓取热门评论（每条作品 Top 20）/ }),
    ).toBeChecked();
    expect(screen.getByRole("combobox", { name: "视频格式" })).toHaveValue("best");
    expect(screen.queryByText("字幕语言")).not.toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "视频格式" }), {
      target: { value: "mp4" },
    });
    expect(onChange).toHaveBeenCalledWith({
      ...DEFAULT_DOWNLOAD_SETTINGS,
      video_format: "mp4",
    });
  });
});
