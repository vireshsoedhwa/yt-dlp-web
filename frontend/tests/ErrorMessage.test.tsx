/**
 * Tests for ErrorMessage component.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ErrorMessage } from "../src/components/ErrorMessage";

describe("ErrorMessage", () => {
  it("should display the error message", () => {
    render(<ErrorMessage message="Something went wrong" />);
    expect(screen.getByText("Something went wrong")).toBeInTheDocument();
  });

  it("should call onDismiss when dismiss button is clicked", async () => {
    const onDismiss = vi.fn();
    const user = userEvent.setup();
    render(<ErrorMessage message="Error" onDismiss={onDismiss} />);

    await user.click(screen.getByLabelText("Dismiss error"));
    expect(onDismiss).toHaveBeenCalledOnce();
  });

  it("should not render dismiss button when onDismiss is not provided", () => {
    render(<ErrorMessage message="Error" />);
    expect(screen.queryByLabelText("Dismiss error")).not.toBeInTheDocument();
  });
});