import type { HTMLAttributes } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/cn";

const badgeVariants = cva("inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs font-medium", {
  variants: {
    variant: {
      neutral: "bg-gray-100 text-gray-600 border-gray-200",
      success: "bg-emerald-50 text-emerald-600 border-emerald-200",
      warning: "bg-amber-50 text-amber-600 border-amber-200",
      info: "bg-primary-50 text-primary-600 border-primary-200",
      danger: "bg-red-50 text-red-600 border-red-200",
    },
  },
  defaultVariants: { variant: "neutral" },
});

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

export default function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
