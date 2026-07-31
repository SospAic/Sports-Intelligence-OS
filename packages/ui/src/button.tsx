import type { ButtonHTMLAttributes } from "react";

type ButtonVariant = "primary" | "secondary" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
}

const variantClasses: Record<ButtonVariant, string> = {
  primary:
    "bg-cyan-300 text-slate-950 hover:bg-cyan-200 focus-visible:outline-cyan-300",
  secondary:
    "border border-slate-700 bg-slate-900 text-slate-100 hover:border-slate-500 focus-visible:outline-slate-400",
  ghost:
    "bg-transparent text-slate-300 hover:bg-slate-800 hover:text-white focus-visible:outline-slate-400",
};

export function Button({
  className = "",
  variant = "primary",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      className={`inline-flex min-h-10 items-center justify-center rounded-lg px-4 py-2 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 ${variantClasses[variant]} ${className}`}
      type={type}
      {...props}
    />
  );
}
