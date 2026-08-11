import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const replaceMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

const loginMock = vi.fn();
vi.mock("@/lib/endpoints", () => ({
  authApi: { login: (...args: unknown[]) => loginMock(...args) },
}));

import LoginPage from "@/app/login/page";

describe("LoginPage", () => {
  beforeEach(() => {
    replaceMock.mockClear();
    loginMock.mockReset();
  });

  it("submits the password in the POST body and redirects to /dashboard on success", async () => {
    loginMock.mockResolvedValue({ data: { authenticated: true } });
    render(<LoginPage />);

    const input = screen.getByLabelText("团队密码");
    await userEvent.type(input, "secret-pass");
    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    await waitFor(() => expect(loginMock).toHaveBeenCalledWith("secret-pass"));
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the server error message and does not redirect on failure", async () => {
    const { ApiError } = await import("@/lib/api-client");
    loginMock.mockRejectedValue(new ApiError(401, { code: "INVALID_CREDENTIALS", message: "密码不正确" }));
    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("团队密码"), "wrong");
    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    expect(await screen.findByRole("alert")).toHaveTextContent("密码不正确");
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("never stores the password field's value anywhere outside the input itself (no window storage writes)", async () => {
    loginMock.mockResolvedValue({ data: { authenticated: true } });
    const setItemSpy = vi.spyOn(Storage.prototype, "setItem");
    render(<LoginPage />);

    await userEvent.type(screen.getByLabelText("团队密码"), "secret-pass");
    await userEvent.click(screen.getByRole("button", { name: /登录/ }));

    await waitFor(() => expect(loginMock).toHaveBeenCalled());
    expect(setItemSpy).not.toHaveBeenCalled();
    setItemSpy.mockRestore();
  });
});
