import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { api } from "../../lib/api";
import { UploadDialog } from "./UploadDialog";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url) => {
      if (url !== "/api/recordings/limits")
        throw new Error(`Unexpected request: ${url}`);
      return Response.json({
        max_upload_bytes: 2_000_000_000,
        max_duration_ms: 7_200_000,
      });
    }),
  );
  vi.spyOn(api, "upload").mockResolvedValue({
    id: "record",
    title: "인터뷰",
    source: "file",
    input_state: "ready",
    duration_ms: 1000,
    created_at: "2026-10-16T00:00:00Z",
    generation: 0,
  });
});

afterEach(() => vi.unstubAllGlobals());

it("rejects files above the limit before transmission", async () => {
  const file = new File(["audio"], "too-large.wav", { type: "audio/wav" });
  Object.defineProperty(file, "size", { value: 2_000_000_001 });
  render(<UploadDialog onClose={() => {}} onSaved={() => {}} />);
  await screen.findByText(/최대 2시간 \/ 2GB/);
  await userEvent.upload(screen.getByLabelText("녹음 파일"), file);
  expect(await screen.findByRole("alert")).toHaveTextContent("2GB");
  expect(api.upload).not.toHaveBeenCalled();
});

it("opens the stored recording after an upload", async () => {
  const saved = vi.fn();
  render(<UploadDialog onClose={() => {}} onSaved={saved} />);
  await screen.findByText(/최대 2시간 \/ 2GB/);
  await userEvent.upload(
    screen.getByLabelText("녹음 파일"),
    new File(["audio"], "interview.wav", { type: "audio/wav" }),
  );
  await waitFor(() => expect(saved).toHaveBeenCalledWith("record"));
});

it.each([1_500_000_000, 2_000_000_000])(
  "accepts a %i byte file within the limit",
  async (size) => {
    const saved = vi.fn();
    const file = new File(["audio"], "large.wav", { type: "audio/wav" });
    Object.defineProperty(file, "size", { value: size });
    render(<UploadDialog onClose={() => {}} onSaved={saved} />);
    await screen.findByText(/최대 2시간 \/ 2GB/);
    await userEvent.upload(screen.getByLabelText("녹음 파일"), file);
    await waitFor(() => expect(saved).toHaveBeenCalledWith("record"));
  },
);

it("uses the server limit for the hint and validation", async () => {
  vi.mocked(fetch).mockResolvedValue(
    Response.json({
      max_upload_bytes: 4_000_000_000,
      max_duration_ms: 7_200_000,
    }),
  );
  render(<UploadDialog onClose={() => {}} onSaved={() => {}} />);
  await screen.findByText(/최대 2시간 \/ 4GB/);
  const file = new File(["audio"], "too-large.wav", { type: "audio/wav" });
  Object.defineProperty(file, "size", { value: 4_000_000_001 });
  await userEvent.upload(screen.getByLabelText("녹음 파일"), file);
  expect(await screen.findByRole("alert")).toHaveTextContent("4GB");
  expect(api.upload).not.toHaveBeenCalled();
});

it("keeps uploads disabled when the server limit cannot be loaded", async () => {
  vi.mocked(fetch).mockRejectedValue(new TypeError("offline"));
  render(<UploadDialog onClose={() => {}} onSaved={() => {}} />);
  expect(await screen.findByRole("alert")).toHaveTextContent("서버");
  expect(screen.getByLabelText("녹음 파일")).toBeDisabled();
});
